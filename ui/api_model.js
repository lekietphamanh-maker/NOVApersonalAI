// The API brain form's model field: which value survives a provider change.
// A provider's default is only ever filled in automatically; a model the owner typed stays theirs,
// even when they switch providers. The page tracks the last automatic value (autoValue) so it can
// tell the two apart: when the field still holds the previous automatic value, it takes the new
// provider's default (or is cleared when the new provider has none); anything else is the owner's
// own value — including an empty field they cleared by hand — and is left alone.
export function nextModelValue(current, autoValue, nextDefault) {
  if (current === autoValue) return nextDefault || "";
  return current;
}
