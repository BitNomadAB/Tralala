const stars = [
  { left: "12%", top: "22%", delay: "-1s" },
  { left: "24%", top: "68%", delay: "-4s" },
  { left: "38%", top: "14%", delay: "-7s" },
  { left: "55%", top: "78%", delay: "-2.5s" },
  { left: "68%", top: "31%", delay: "-6s" },
  { left: "81%", top: "62%", delay: "-8s" },
  { left: "90%", top: "18%", delay: "-3.5s" },
  { left: "47%", top: "48%", delay: "-5s" },
];

/** Fixed, non-interactive background: breathing grid, drifting colour fields and slow stars. */
export function AmbientBackground() {
  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient-grid" />
      <div className="ambient-glow" />
      <div className="ambient-lights" />
      <div className="ambient-blob" />
      <div className="ambient-blob" />
      <div className="ambient-blob" />
      {stars.map((star) => (
        <span
          key={`${star.left}-${star.top}`}
          className="ambient-star"
          style={{ left: star.left, top: star.top, animationDelay: star.delay }}
        />
      ))}
    </div>
  );
}
