// Temporal graph evolution player controller: timeline slider and step animation.

export function createTimelinePlayer({
  dates = [],
  onDateChange = () => {},
  stepIntervalMs = 700,
}) {
  let currentIndex = dates.length > 0 ? dates.length - 1 : 0;
  let timerId = null;
  let isPlaying = false;

  function setIndex(idx) {
    if (dates.length === 0) return;
    currentIndex = Math.max(0, Math.min(dates.length - 1, idx));
    onDateChange(dates[currentIndex], currentIndex, dates.length);
  }

  function next() {
    if (currentIndex < dates.length - 1) {
      setIndex(currentIndex + 1);
    } else {
      pause();
    }
  }

  function prev() {
    if (currentIndex > 0) {
      setIndex(currentIndex - 1);
    }
  }

  function play() {
    if (isPlaying || dates.length === 0) return;
    if (currentIndex >= dates.length - 1) {
      currentIndex = 0;
    }
    isPlaying = true;
    timerId = setInterval(() => {
      if (currentIndex >= dates.length - 1) {
        pause();
      } else {
        next();
      }
    }, stepIntervalMs);
  }

  function pause() {
    isPlaying = false;
    if (timerId) {
      clearInterval(timerId);
      timerId = null;
    }
  }

  function toggle() {
    if (isPlaying) {
      pause();
    } else {
      play();
    }
    return isPlaying;
  }

  function destroy() {
    pause();
  }

  return {
    play,
    pause,
    toggle,
    next,
    prev,
    setIndex,
    getIndex: () => currentIndex,
    getDate: () => dates[currentIndex],
    isPlaying: () => isPlaying,
    destroy,
  };
}
