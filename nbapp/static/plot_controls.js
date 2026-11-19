"use strict";
NB.plotControls = (() => {
  const PRINT_WIDTH = 1200;
  const gainStep = (gain, steps) => Math.max(0.25, Math.min(1024, gain * 2 ** steps));
  const wheelStep = (delta, over) => over && delta !== 0 && Number.isFinite(delta) ? -Math.sign(delta) / 4 : 0;
  const fullKey = (e, active, editing) => active && !editing && e.key.toLowerCase() === "f" &&
    !e.altKey && !e.ctrlKey && !e.metaKey && !e.isComposing;
  const primary = e => e.button === 0 && e.isPrimary !== false;
  function hitEdge(x, y, edges, radius = 5) {
    let best = null, distance = radius;
    for (const edge of edges) {
      if (y < edge.top || y > edge.bottom) continue;
      const d = Math.abs(edge.x - x);
      if (d <= distance) { best = edge; distance = d; }
    }
    return best;
  }
  const width = (screenWidth, printing) => printing ? PRINT_WIDTH : screenWidth;
  return { gainStep, wheelStep, fullKey, primary, hitEdge, width };
})();
