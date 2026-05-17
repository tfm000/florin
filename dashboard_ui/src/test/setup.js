// Vitest setup file — applied to every test via vitest.config.js setupFiles.
//
// recharts (and many other UI libs) measure their container with
// ResizeObserver, IntersectionObserver, and getBoundingClientRect. jsdom
// provides none of these by default, so without these stubs every chart
// component test would silently render at 0x0 and produce confusing
// assertions. Baked in here so future chart tests don't have to rediscover
// the gotcha.

import '@testing-library/jest-dom/vitest'

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

global.IntersectionObserver = class IntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

if (typeof Element !== 'undefined') {
  Element.prototype.getBoundingClientRect = function () {
    return {
      width: 400,
      height: 300,
      top: 0,
      left: 0,
      bottom: 300,
      right: 400,
      x: 0,
      y: 0,
      toJSON() {},
    }
  }
}
