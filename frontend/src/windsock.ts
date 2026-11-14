import * as THREE from 'three';

type Wind = { headwind_mps: number; crosswind_mps: number; vertical_wind_mps?: number };

export function createWindsock() {
  const object = new THREE.Group();
  object.name = 'runway-windsock';
  object.position.set(8, 0, -28);
  const metal = new THREE.MeshStandardMaterial({color: 0xb6b9b3, metalness: .65, roughness: .5});
  const base = new THREE.Mesh(new THREE.CylinderGeometry(.6, .75, .25, 16),
    new THREE.MeshStandardMaterial({color: 0x78746b, roughness: .95}));
  base.position.y = .125;
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(.065, .11, 7.5, 12), metal);
  mast.position.y = 3.75;
  object.add(base, mast);
  const swivel = new THREE.Group();
  swivel.position.y = 7.1;
  object.add(swivel);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(.48, .018, 6, 32), metal);
  rim.rotation.y = Math.PI / 2;
  rim.position.x = .65;
  swivel.add(rim);
  const cords: number[] = [];
  for (let i = 0; i < 4; i++) {
    const a = i * Math.PI / 2;
    cords.push(0, 0, 0, .65, Math.cos(a) * .48, Math.sin(a) * .48);
  }
  swivel.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(cords, 3)), new THREE.LineBasicMaterial({color: 0x737d78})));

  const rings = 25, sides = 12;
  const positions = new Float32Array(rings * (sides + 1) * 3);
  const colors = new Float32Array(positions.length);
  const indices: number[] = [];
  const red = new THREE.Color(0xd84d48), cream = new THREE.Color(0xf5ecd5);
  for (let i = 0; i < rings; i++) {
    const color = Math.floor(i / (rings - 1) * 5) % 2 ? cream : red;
    for (let j = 0; j <= sides; j++) {
      color.toArray(colors, (i * (sides + 1) + j) * 3);
      if (i < rings - 1 && j < sides) {
        const a = i * (sides + 1) + j, b = a + sides + 1;
        indices.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  const vertices = new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute('position', vertices);
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setIndex(indices);
  const cloth = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    vertexColors: true, side: THREE.DoubleSide, roughness: .92,
  }));
  cloth.name = 'windsock-cloth';
  cloth.position.x = .65;
  cloth.frustumCulled = false;
  swivel.add(cloth);
  object.traverse(child => {if (child instanceof THREE.Mesh) child.castShadow = true;});
  let heading = 0, speed = 0, vertical = 0;

  function update(wind: Wind, time: number, dt: number, reducedMotion: boolean) {
    // shortcut: observed wind is at aircraft altitude; sample surface wind for ground-weather fidelity.
    const targetSpeed = Math.hypot(wind.headwind_mps, wind.crosswind_mps);
    const damping = 1 - Math.exp(-Math.min(dt, .1) * 3);
    // Northbound runway: +X north/forward, +Z east/right; wind values describe FROM.
    if (targetSpeed > .05) {
      const target = Math.atan2(-wind.crosswind_mps, -wind.headwind_mps);
      heading += Math.atan2(Math.sin(target - heading), Math.cos(target - heading)) * damping;
    }
    speed += (targetSpeed - speed) * damping;
    vertical += ((wind.vertical_wind_mps ?? 0) - vertical) * damping;
    swivel.rotation.y = heading;
    const lift = .035 + .965 * Math.min(speed / 7, 1);
    const flutter = reducedMotion ? 0 : Math.min(speed / 8, 1) * .11;
    for (let i = 0; i < rings; i++) {
      const u = i / (rings - 1), wave = Math.sin(time * (5 + speed * .35) - u * 9);
      const radius = (.48 - .32 * u) * (1 - .42 * (1 - lift) * u);
      const bend = (1 - lift) * u * Math.PI / 2;
      const x = 4 * u * lift;
      const y = -3.6 * u * (1 - lift) - .3 * u * u + vertical * .07 * u;
      for (let j = 0; j <= sides; j++) {
        const a = j / sides * Math.PI * 2, radial = radius * Math.cos(a);
        vertices.setXYZ(i * (sides + 1) + j,
          x + radial * Math.sin(bend),
          y + radial * Math.cos(bend) + flutter * u * u * wave * .45,
          radius * Math.sin(a) + flutter * u * u * wave);
      }
    }
    vertices.needsUpdate = true;
    geometry.computeVertexNormals();
  }
  update({headwind_mps: 0, crosswind_mps: 0}, 0, 0, true);
  return {object, update,
    get flowBearingDeg() { return ((-heading * 180 / Math.PI) % 360 + 360) % 360; },
    get speedMps() { return speed; },
    get verticalMps() { return vertical; },
  };
}
