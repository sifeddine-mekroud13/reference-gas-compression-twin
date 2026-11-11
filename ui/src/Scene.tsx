import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { AssetContext } from "./api";

export interface EqProps { tag: string; cls: string; type: string; pos: [number, number, number]; ds: Record<string, number> }

function Controls() {
  const { camera, gl } = useThree();
  useEffect(() => {
    const c = new OrbitControls(camera, gl.domElement);
    c.target.set(10, 0, 8);
    c.update();
    return () => c.dispose();
  }, [camera, gl]);
  return null;
}

const GREY = "#9a9a9a", SEL = "#3b6fb6", ALARM = "#d08a00";

// three.js is y-up; plant layout is z-up (x east, y north). Map (x, y, z) -> (x, z, -y).
const v = (p: [number, number, number]) => new THREE.Vector3(p[0], p[2], -p[1]);

function Item({ e, selected, alarm, onPick }: { e: EqProps; selected: boolean; alarm: boolean; onPick: (id: string) => void }) {
  const color = selected ? SEL : alarm ? ALARM : GREY;
  const p = v(e.pos);
  const pick = (ev: { stopPropagation: () => void }) => { ev.stopPropagation(); onPick(`equipment:${e.tag}`); };
  const mat = <meshStandardMaterial color={color} metalness={0.3} roughness={0.6} />;
  if (e.cls === "VE") {
    const d = e.ds.internal_diameter_m ?? 2, h = e.ds.tan_tan_height_m ?? 6;
    return <mesh position={[p.x, p.y + h / 2, p.z]} onClick={pick}><cylinderGeometry args={[d / 2, d / 2, h, 32]} />{mat}</mesh>;
  }
  if (e.cls === "CO") return <mesh position={[p.x, p.y + 1.4, p.z]} onClick={pick}><boxGeometry args={[4.5, 2.2, 2.4]} />{mat}</mesh>;
  if (e.cls === "EM" && e.type !== "fan_motor")
    return <mesh position={[p.x, p.y + 1.4, p.z]} rotation={[0, 0, Math.PI / 2]} onClick={pick}><cylinderGeometry args={[1.1, 1.1, 3, 24]} />{mat}</mesh>;
  if (e.cls === "EM")
    return <mesh position={[p.x, p.y, p.z]} onClick={pick}><cylinderGeometry args={[1.6, 1.6, 0.3, 24]} />{mat}</mesh>;
  if (e.cls === "HE") {
    const bays = e.ds.bays ?? 2;
    return (
      <group onClick={pick}>
        <mesh position={[p.x, p.y + 0.5, p.z]}><boxGeometry args={[6 * bays, 1, 10]} />{mat}</mesh>
        {[-1, 1].flatMap((sx) => [-1, 1].map((sz) => (
          <mesh key={`${sx}${sz}`} position={[p.x + sx * 3 * bays - sx * 0.3, p.y / 2, p.z + sz * 4.7]}>
            <boxGeometry args={[0.3, p.y, 0.3]} /><meshStandardMaterial color="#777" />
          </mesh>)))}
      </group>
    );
  }
  return <mesh position={[p.x, p.y + 0.4, p.z]} onClick={pick}><boxGeometry args={[0.8, 0.8, 0.8]} />{mat}</mesh>;
}

function Pipe({ a, b, dn }: { a: THREE.Vector3; b: THREE.Vector3; dn: number }) {
  const geo = useMemo(() => {
    const mid1 = new THREE.Vector3(a.x, 2.5, a.z), mid2 = new THREE.Vector3(b.x, 2.5, b.z);
    const path = new THREE.CurvePath<THREE.Vector3>();
    [[a, mid1], [mid1, mid2], [mid2, b]].forEach(([s, t]) => path.add(new THREE.LineCurve3(s, t)));
    return new THREE.TubeGeometry(path as unknown as THREE.Curve<THREE.Vector3>, 48, Math.max(dn / 2000, 0.05), 8, false);
  }, [a, b, dn]);
  return <mesh geometry={geo}><meshStandardMaterial color="#b5b5b5" /></mesh>;
}

export function Scene({ equipment, lines, selected, alarmed, onPick }: {
  equipment: EqProps[]; lines: { from: string; to: string; dn: number }[]; selected: string | null;
  alarmed: Set<string>; onPick: (id: string) => void;
}) {
  const pos = (end: string): THREE.Vector3 | null => {
    const [k] = end.split(":");
    const e = equipment.find((x) => x.tag === k);
    if (e) return v(e.pos).add(new THREE.Vector3(0, 1, 0));
    const fixed: Record<string, [number, number, number]> = {
      "J:J-01": [-4, 0, 1], "J:J-02": [22, 18, 1], "BL:FEED": [-15, 0, 1], "BL:EXPORT": [35, 18, 1], "BL:DRAIN": [-6, 6, 0.5] };
    return fixed[end] ? v(fixed[end]) : null;
  };
  return (
    <Canvas camera={{ position: [-20, 25, 30], fov: 45 }} style={{ background: "#d9d9d9" }} onPointerMissed={() => onPick("")}>
      <ambientLight intensity={0.6} /><directionalLight position={[20, 40, 10]} intensity={1.1} />
      <gridHelper args={[80, 40, "#bbb", "#ccc"]} />
      {equipment.map((e) => (
        <Item key={e.tag} e={e} selected={selected === `equipment:${e.tag}`} alarm={alarmed.has(e.tag)} onPick={onPick} />
      ))}
      {lines.map((l, i) => { const a = pos(l.from), b = pos(l.to); return a && b ? <Pipe key={i} a={a} b={b} dn={l.dn} /> : null; })}
      <Controls />
    </Canvas>
  );
}

export function contextTitle(c: AssetContext | null): string {
  return c ? `${c.node.name} (${c.node.kind})` : "Select an object in 3D or on the P&ID";
}
