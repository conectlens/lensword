import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber'
import { Billboard, OrbitControls, Text } from '@react-three/drei'
import { useEffect } from 'react'
import { ROOM_SIZE, floorToPercent, percentToFloor } from '../../lib/roomSpace'
import type { Room, Word } from '../../lib/types'

/**
 * The Mind Palace room as a space you can walk your eye around (issue #339).
 *
 * **Default-exported and imported through `React.lazy`.** three.js and its
 * React bindings are a large dependency, and the rest of the app has no use
 * for them — this module is the code-split boundary that keeps them out of
 * the main bundle for everyone who never opens a room.
 *
 * **Placements are the same rows the 2D board writes.** Click the floor to
 * place the selected word; the point is converted straight back to the
 * `x_percent`/`y_percent` the existing endpoint already takes, so nothing
 * about persistence changes and the two views cannot disagree.
 */

/** Frees GPU memory when the room unmounts. */
function DisposeOnUnmount() {
  const { gl } = useThree()
  useEffect(() => {
    // Without this the WebGL context survives navigation, and a few visits
    // are enough for a browser to start dropping the oldest context —
    // which shows up as a room that renders blank for no visible reason.
    return () => gl.dispose()
  }, [gl])
  return null
}

function WordMarker({
  label,
  position,
  onRemove,
}: {
  label: string
  position: [number, number]
  onRemove: () => void
}) {
  const [x, z] = position
  return (
    <group position={[x, 0, z]}>
      <mesh
        position={[0, 0.35, 0]}
        onClick={(event: ThreeEvent<MouseEvent>) => {
          // Without this the click continues to the floor behind the marker
          // and immediately re-places the word where it already is.
          event.stopPropagation()
          onRemove()
        }}
      >
        <cylinderGeometry args={[0.18, 0.18, 0.7, 16]} />
        <meshStandardMaterial color="#7c5cff" />
      </mesh>

      {/* Billboarded so a label is readable from wherever the camera is;
          text fixed to the floor plane would be edge-on half the time. */}
      <Billboard position={[0, 1.1, 0]}>
        <Text fontSize={0.34} color="white" anchorX="center" anchorY="middle" outlineWidth={0.012} outlineColor="#000">
          {label}
        </Text>
      </Billboard>
    </group>
  )
}

export default function RoomScene3D({
  room,
  wordById,
  selectedWordId,
  onPlace,
  onRemove,
}: {
  room: Room
  wordById: Map<number, Word>
  selectedWordId: number | null
  onPlace: (xPercent: number, yPercent: number) => void
  onRemove: (wordId: number) => void
}) {
  return (
    <Canvas camera={{ position: [0, 8, 11], fov: 45 }} className="rounded-lg">
      <DisposeOnUnmount />

      <ambientLight intensity={0.7} />
      <directionalLight position={[5, 10, 5]} intensity={1.1} />

      {/* The floor is the placement surface: a click anywhere on it drops
          the selected word at that point. */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        onClick={(event: ThreeEvent<MouseEvent>) => {
          if (selectedWordId == null) return
          const { x_percent, y_percent } = floorToPercent(event.point.x, event.point.z)
          onPlace(x_percent, y_percent)
        }}
      >
        <planeGeometry args={[ROOM_SIZE, ROOM_SIZE]} />
        <meshStandardMaterial color="#1b1b2b" />
      </mesh>

      <gridHelper args={[ROOM_SIZE, 10, '#3b3b55', '#2a2a3d']} />

      {room.placements.map((placement) => {
        const word = wordById.get(placement.word_id)
        if (!word) return null
        return (
          <WordMarker
            key={placement.word_id}
            label={word.term}
            position={percentToFloor(placement.x_percent, placement.y_percent)}
            onRemove={() => onRemove(placement.word_id)}
          />
        )
      })}

      {/* Orbit, not free flight: the room is a memory aid people need to
          re-recognise, and a camera that can end up anywhere makes the same
          room look different every visit. */}
      <OrbitControls enablePan={false} minDistance={4} maxDistance={20} maxPolarAngle={Math.PI / 2.2} />
    </Canvas>
  )
}
