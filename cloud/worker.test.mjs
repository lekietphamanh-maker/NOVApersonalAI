// The relay with a fake KV store and fake Telegram / Claude: node --test cloud/worker.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { everyMinute, systemPrompt } from "./worker.js";

const OWNER = 1001;

function setup(brain = "claude") {
  const store = new Map();
  const calls = [];
  const env = {
    NOVA: {
      get: async (key) => (store.has(key) ? store.get(key) : null),
      put: async (key, value) => { store.set(key, value); },
      delete: async (key) => { store.delete(key); },
    },
    SELF_URL: "https://nova-telegram.example.workers.dev", BOT_TOKEN: "123:ABC", HOOK_SECRET: "hook-secret",
    PC_SECRET: "pc-secret", BRAIN: brain, BRAIN_KEY: "key", BRAIN_MODEL: "",
  };
  globalThis.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    calls.push({ url: String(url), body, headers: options.headers });
    if (String(url).startsWith("https://api.anthropic.com")) {
      return Response.json({ content: [{ type: "text", text: "Sure, here's a plan." }] });
    }
    return Response.json({ ok: true, result: true });
  };
  return { env, store, calls };
}

const pcSync = (env, body, secret = "pc-secret") => worker.fetch(new Request("https://relay/pc/sync", {
  method: "POST", headers: { Authorization: `Bearer ${secret}` }, body: JSON.stringify(body) }), env);

const fromTelegram = (env, message, secret = "hook-secret") => worker.fetch(new Request("https://relay/telegram", {
  method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": secret }, body: JSON.stringify({ update_id: 1, message }) }), env);

const ownerSays = (text, extra = {}) => ({ chat: { id: OWNER, type: "private" }, from: { id: OWNER, is_bot: false }, text, ...extra });

test("only the PC with its secret checks in", async () => {
  const { env, store } = setup();
  assert.equal((await pcSync(env, { owner: OWNER }, "wrong")).status, 401);
  assert.equal(store.has("pc"), false);
  const answer = await (await pcSync(env, { owner: OWNER, name: "Sam", facts: ["likes tea"] })).json();
  assert.deepEqual(answer, { away: [], delivered: [] });
  assert.equal(JSON.parse(store.get("pc")).name, "Sam");
});

test("while the PC is on the relay stays out of the way", async () => {
  const { env, calls } = setup();
  await pcSync(env, { owner: OWNER, reminders: [{ key: "1@x", text: "stretch", due: Date.now() / 1000 - 30 }] });
  await everyMinute(env, Date.now());
  assert.deepEqual(calls, []); // no webhook, no reminder: the PC says them
});

test("a PC that shuts down hands Telegram to the relay at once", async () => {
  const { env, store, calls } = setup();
  await pcSync(env, { owner: OWNER, going: true });
  assert.equal(calls[0].url, "https://api.telegram.org/bot123:ABC/setWebhook");
  assert.deepEqual(calls[0].body, { url: "https://nova-telegram.example.workers.dev/telegram", secret_token: "hook-secret",
                                     allowed_updates: ["message"] });
  assert.equal(store.get("hook"), "on");
});

test("a PC that stops checking in is taken over, and reminders still come on time", async () => {
  const { env, store, calls } = setup();
  const checkedIn = Date.now() - 20 * 60_000;
  const due = Math.floor((checkedIn + 5 * 60_000) / 1000);
  store.set("pc", JSON.stringify({ seen: checkedIn, off: false, owner: OWNER, name: "", facts: [], offset: 0,
    reminders: [{ key: "1@a", text: "call mom", due }, { key: "2@b", text: "later", due: due + 86_400 },
                { key: "3@c", text: "said by the PC already", due: Math.floor(checkedIn / 1000) - 60 }] }));
  await everyMinute(env, Date.now());
  await everyMinute(env, Date.now()); // the next minute: nothing twice
  const sent = calls.filter((call) => call.url.endsWith("/sendMessage")).map((call) => call.body.text);
  assert.deepEqual(sent, ["Reminder: call mom"]);
  assert.equal(calls.filter((call) => call.url.endsWith("/setWebhook")).length, 1);
  assert.deepEqual(JSON.parse(store.get("delivered")), ["1@a"]);
  const back = await (await pcSync(env, { owner: OWNER })).json(); // the PC is back: it learns what was sent
  assert.deepEqual(back.delivered, ["1@a"]);
  assert.equal(store.get("hook"), "off");
});

test("while the PC is off the owner gets answers, everyone else gets nothing", async () => {
  const { env, store, calls } = setup();
  await pcSync(env, { owner: OWNER, name: "Sam", facts: ["plays the piano"], going: true });
  calls.length = 0;
  assert.equal((await fromTelegram(env, ownerSays("hi"), "forged")).status, 401);
  await fromTelegram(env, { chat: { id: 7, type: "private" }, from: { id: 7 }, text: "hello?" });
  await fromTelegram(env, { ...ownerSays("group"), chat: { id: -5, type: "group" } });
  assert.deepEqual(calls, []);
  await fromTelegram(env, ownerSays("plan my evening"));
  const claude = calls.find((call) => call.url.startsWith("https://api.anthropic.com"));
  assert.equal(claude.body.model, "claude-haiku-5-5");
  assert.match(claude.body.system, /Sam/);
  assert.match(claude.body.system, /plays the piano/);
  assert.deepEqual(claude.body.messages, [{ role: "user", content: "plan my evening" }]);
  assert.equal(calls.at(-1).body.text, "Sure, here's a plan.");
  const away = JSON.parse(store.get("away"));
  assert.equal(away[0].text, "plan my evening");
  await fromTelegram(env, ownerSays("and tomorrow?"));
  const second = calls.filter((call) => call.url.startsWith("https://api.anthropic.com"))[1];
  assert.equal(second.body.messages.length, 3); // the earlier exchange comes along
  const back = await (await pcSync(env, { owner: OWNER })).json();
  assert.deepEqual(back.away.map((item) => item.text), ["plan my evening", "and tomorrow?"]);
  assert.equal(store.has("away"), false);
});

test("without an online brain, and for voice notes, the relay says the PC is off", async () => {
  const { env, calls } = setup("none");
  await pcSync(env, { owner: OWNER, going: true });
  await fromTelegram(env, ownerSays("hello"));
  assert.match(calls.at(-1).body.text, /PC is off/);
  await fromTelegram(env, ownerSays("", { voice: { file_id: "v" } }));
  assert.match(calls.at(-1).body.text, /voice notes are heard on it/);
});

test("the prompt keeps Nova honest about what she can do from the cloud", () => {
  const prompt = systemPrompt({ name: "", facts: [], offset: 420 });
  assert.match(prompt, /can't use the PC/);
  assert.doesNotMatch(prompt, /owner's name/);
});
