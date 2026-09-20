// Flow particle animation controller on 2D canvas overlay with idle-pausing.

export function createParticleController({
  canvas,
  stage,
  graph,
  renderer,
  getDark,
  isNodeVisible,
  isEdgeVisible
}) {
  if (!canvas || !stage) {
    return {
      updateSize: () => {},
      checkState: () => {},
      stop: () => {},
    };
  }

  let particleOffset = 0;
  let particleRaf = 0;
  let particlesRunning = false;
  let currentSelected = null;
  let currentPathMode = false;
  let currentPathEdgeSet = new Set();

  function updateSize() {
    const targetW = stage.clientWidth || 800;
    const targetH = stage.clientHeight || 600;
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }
  }

  function render() {
    if (!particlesRunning) return;
    updateSize();
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    let activeEdges = [];
    if (currentPathMode && currentPathEdgeSet && currentPathEdgeSet.size) {
      activeEdges = [...currentPathEdgeSet];
    } else if (currentSelected) {
      activeEdges = graph.edges(currentSelected).filter(e => isEdgeVisible(e));
    }

    if (activeEdges.length > 0 && activeEdges.length <= 40) {
      particleOffset = (particleOffset + 0.014) % 1;
      const isDark = typeof getDark === 'function' ? getDark() : true;
      ctx.fillStyle = isDark ? '#38bdf8' : '#0284c7';
      ctx.shadowColor = isDark ? '#38bdf8' : '#0284c7';
      ctx.shadowBlur = 5;

      for (const e of activeEdges) {
        const [s, t] = graph.extremities(e);
        if (!isNodeVisible(s) || !isNodeVisible(t)) continue;
        const sa = graph.getNodeAttributes(s);
        const ta = graph.getNodeAttributes(t);
        const sp = renderer.graphToViewport(sa);
        const tp = renderer.graphToViewport(ta);

        const px = sp.x + (tp.x - sp.x) * particleOffset;
        const py = sp.y + (tp.y - sp.y) * particleOffset;

        ctx.beginPath();
        ctx.arc(px, py, 2.8, 0, Math.PI * 2);
        ctx.fill();
      }
      particleRaf = requestAnimationFrame(render);
    } else {
      particlesRunning = false;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  function checkState(selected, pathMode, pathEdgeSet) {
    currentSelected = selected;
    currentPathMode = pathMode;
    currentPathEdgeSet = pathEdgeSet || new Set();

    const hasParticles = (currentPathMode && currentPathEdgeSet && currentPathEdgeSet.size > 0) || !!currentSelected;
    if (hasParticles && !particlesRunning) {
      particlesRunning = true;
      cancelAnimationFrame(particleRaf);
      particleRaf = requestAnimationFrame(render);
    } else if (!hasParticles && particlesRunning) {
      particlesRunning = false;
      cancelAnimationFrame(particleRaf);
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  function stop() {
    particlesRunning = false;
    cancelAnimationFrame(particleRaf);
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  return {
    updateSize,
    checkState,
    stop,
  };
}
