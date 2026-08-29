import { useEffect, useMemo, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

const CUBE_SIZE = 2;
const HALF = CUBE_SIZE / 2;
const MIN_RADIUS = 0.018;
const MAX_RADIUS = 0.045;
// Quantization step (0-255) used to bucket similar sampled colors together
// when estimating per-point frequency weight — the backend sends raw,
// unweighted pixel samples, so "common colors" are inferred client-side.
const WEIGHT_BUCKET = 16;

// Matches the R/G/B channel colors used in RGBHistogram (Tailwind red/green/blue-500).
const AXIS_COLORS = { r: "#ef4444", g: "#22c55e", b: "#3b82f6" };

interface ColorSpaceCloudProps {
  samples: number[][];
}

/** Centroid of the sampled colors, mapped into the same cube space the
 * points themselves are plotted in (see PointCloud below) — so the camera
 * and OrbitControls can center on where the data actually sits instead of
 * the cube's geometric middle, which is often mostly empty space. */
function computeCentroid(samples: number[][]): THREE.Vector3 {
  if (samples.length === 0) return new THREE.Vector3(0, 0, 0);
  const sum = samples.reduce(
    (acc, [r, g, b]) => {
      acc.x += r / 255;
      acc.y += g / 255;
      acc.z += b / 255;
      return acc;
    },
    { x: 0, y: 0, z: 0 },
  );
  const n = samples.length;
  return new THREE.Vector3(
    (sum.x / n) * CUBE_SIZE - HALF,
    (sum.y / n) * CUBE_SIZE - HALF,
    (sum.z / n) * CUBE_SIZE - HALF,
  );
}

export function ColorSpaceCloud({ samples }: ColorSpaceCloudProps) {
  const centroid = useMemo(() => computeCentroid(samples), [samples]);

  if (samples.length === 0) {
    return null;
  }

  return (
    <div className="border-t border-border pt-4">
      <span className="font-mono text-[10px] uppercase tracking-widest text-muted">
        Color space
      </span>
      <div className="mt-2 h-[480px] w-full border border-[#e0e0e0] bg-transparent shadow-[0_1px_3px_rgba(0,0,0,0.08)]">
        <Canvas
          camera={{
            position: [centroid.x + 2.2, centroid.y + 1.6, centroid.z + 2.2],
            fov: 45,
          }}
          dpr={[1, 2]}
        >
          <ambientLight intensity={0.6} />
          <directionalLight position={[3, 4, 2]} intensity={0.8} />
          <PointCloud samples={samples} />
          <CubeFrame />
          <GridFloor />
          <AxisTicks />
          <OrbitControls
            target={[centroid.x, centroid.y, centroid.z]}
            enablePan={false}
            enableDamping
            dampingFactor={0.08}
            autoRotate
            autoRotateSpeed={1.5}
            minDistance={2.5}
            maxDistance={7}
          />
        </Canvas>
      </div>
      <p className="mt-2 font-mono text-[10px] uppercase tracking-wide text-muted">
        Color space — {samples.length} pixels plotted in RGB space — drag to rotate
      </p>
    </div>
  );
}

/** Normalized [0,1] frequency weight per sample, bucketed by nearby RGB values. */
function computeWeights(samples: number[][]): number[] {
  const counts = new Map<string, number>();
  const keys = samples.map(([r, g, b]) => {
    const key = `${Math.round(r / WEIGHT_BUCKET)}-${Math.round(g / WEIGHT_BUCKET)}-${Math.round(b / WEIGHT_BUCKET)}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
    return key;
  });
  const max = Math.max(...counts.values());
  return keys.map((k) => {
    const count = counts.get(k)!;
    return max > 1 ? (count - 1) / (max - 1) : 0;
  });
}

function PointCloud({ samples }: { samples: number[][] }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const weights = useMemo(() => computeWeights(samples), [samples]);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    samples.forEach(([r, g, b], i) => {
      dummy.position.set(
        (r / 255) * CUBE_SIZE - HALF,
        (g / 255) * CUBE_SIZE - HALF,
        (b / 255) * CUBE_SIZE - HALF,
      );
      const radius = MIN_RADIUS + weights[i] * (MAX_RADIUS - MIN_RADIUS);
      dummy.scale.setScalar(radius);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      color.setRGB(r / 255, g / 255, b / 255);
      mesh.setColorAt(i, color);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [samples, weights]);

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, samples.length]}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshStandardMaterial roughness={0.5} />
    </instancedMesh>
  );
}

function CubeFrame() {
  const geometry = useMemo(
    () => new THREE.EdgesGeometry(new THREE.BoxGeometry(CUBE_SIZE, CUBE_SIZE, CUBE_SIZE)),
    [],
  );
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color="#000000" transparent opacity={0.15} />
    </lineSegments>
  );
}

/** Reference grid on the cube's bottom face (Y = -HALF), lines every 0.25 units. */
function GridFloor() {
  const segments = useMemo(() => {
    const step = 0.25;
    const lines: [THREE.Vector3, THREE.Vector3][] = [];
    for (let v = -HALF; v <= HALF + 1e-6; v += step) {
      lines.push([new THREE.Vector3(v, -HALF, -HALF), new THREE.Vector3(v, -HALF, HALF)]);
      lines.push([new THREE.Vector3(-HALF, -HALF, v), new THREE.Vector3(HALF, -HALF, v)]);
    }
    return lines;
  }, []);

  return (
    <>
      {segments.map((points, i) => (
        <Line
          key={i}
          points={points}
          color="#000000"
          transparent
          opacity={0.06}
          lineWidth={0.5}
        />
      ))}
    </>
  );
}

function AxisTicks() {
  const origin: [number, number, number] = [-HALF, -HALF, -HALF];
  const labelOffset = 0.4;
  return (
    <>
      <Line points={[origin, [HALF, -HALF, -HALF]]} color={AXIS_COLORS.r} lineWidth={1.5} />
      <Line points={[origin, [-HALF, HALF, -HALF]]} color={AXIS_COLORS.g} lineWidth={1.5} />
      <Line points={[origin, [-HALF, -HALF, HALF]]} color={AXIS_COLORS.b} lineWidth={1.5} />
      <Html position={[HALF + labelOffset, -HALF, -HALF]} center distanceFactor={6}>
        <span className="font-mono text-sm font-semibold" style={{ color: AXIS_COLORS.r }}>
          R
        </span>
      </Html>
      <Html position={[-HALF, HALF + labelOffset, -HALF]} center distanceFactor={6}>
        <span className="font-mono text-sm font-semibold" style={{ color: AXIS_COLORS.g }}>
          G
        </span>
      </Html>
      <Html position={[-HALF, -HALF, HALF + labelOffset]} center distanceFactor={6}>
        <span className="font-mono text-sm font-semibold" style={{ color: AXIS_COLORS.b }}>
          B
        </span>
      </Html>
    </>
  );
}
