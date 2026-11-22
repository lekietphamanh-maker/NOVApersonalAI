// The bench's lighting: a soft-box photo studio rendered into a PMREM environment map.
import * as THREE from '../vendor/three.module.js';

/** Soft-box photo studio rendered into a PMREM environment map (warm cream room + bright panels). */
export function studioEnv(renderer) {
  const sc = new THREE.Scene();
  const room = new THREE.Mesh(new THREE.BoxGeometry(40, 24, 40), new THREE.MeshBasicMaterial({ color: new THREE.Color(1.08, 1.04, 0.97), side: THREE.BackSide }));
  room.position.y = 8; sc.add(room);
  const panel = (w, h, x, y, z, k, tint = [1, 1, 1]) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(tint[0] * k, tint[1] * k, tint[2] * k), side: THREE.DoubleSide }));
    m.position.set(x, y, z); m.lookAt(0, 0, 0); sc.add(m);
  };
  panel(16, 12, 0, 19, 2, 4.2, [1, 0.97, 0.92]);     // overhead soft box
  panel(10, 12, -16, 9, -11, 6.5, [1, 0.95, 0.88]);       // key (front-left)
  panel(6, 14, 17, 6, 8, 3.5, [0.9, 0.95, 1]);        // cool rim (right)
  panel(12, 3, 0, 5, -19, 2.5, [1, 1, 1]);             // back strip
  // dark cards: give polished metal something to contrast against
  const card = (w, h, x, y, z) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.1, 0.1, 0.1), side: THREE.DoubleSide })); m.position.set(x, y, z); m.lookAt(0, 0, 0); sc.add(m); };
  card(3, 16, 19, 6, 14); card(3, 16, -19, 6, 2); card(14, 2.5, 4, 3, 19); card(10, 2, -6, 12, -19);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.42, 0.4, 0.36) }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -3.9; sc.add(floor);
  const pm = new THREE.PMREMGenerator(renderer);
  const tex = pm.fromScene(sc, 0.03).texture;
  pm.dispose(); sc.traverse(o => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
  return tex;
}
