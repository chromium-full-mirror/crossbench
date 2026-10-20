// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// See select_element.js.README.md for an explanation of this script.

const args = arguments[0] || {};

let elements = [];
let element = null;

if (args.selector) {
  if (args.selector.startsWith('xpath/')) {
    const xpath = args.selector.slice('xpath/'.length);
    const xpathResult = document.evaluate(
        xpath, document, null, XPathResult.ORDERED_NODE_ITERATOR_TYPE, null);
    let current = xpathResult.iterateNext();
    while (current) {
      elements.push(current);
      current = xpathResult.iterateNext();
    }
  } else {
    elements = Array.from(document.querySelectorAll(args.selector));
  }
  element = elements[0] || null;
} else {
  elements = [window];
  element = window;
}

let bottom_inset = 0;
let inset_probe = null;
if (window.screenY === 0 && window.outerHeight === screen.height) {
  const cache = window.__crossbench_inset_cache;
  if (cache && cache.outerH === window.outerHeight &&
      cache.innerH === window.visualViewport.height) {
    bottom_inset = cache.value;
  } else {
    inset_probe = document.createElement('div');
    inset_probe.style.cssText =
        'position:fixed;top:0;left:0;width:0;visibility:hidden;' +
        'pointer-events:none;contain:layout style paint;' +
        'height:calc(env(safe-area-max-inset-bottom, 0px) - ' +
        'env(safe-area-inset-bottom, 0px))';
    document.documentElement.appendChild(inset_probe);
  }
}

if (element && element !== window && args.scrollIntoView) {
  element.scrollIntoView({block: 'nearest'});
}

let element_rect =
    (element && element !== window) ? element.getBoundingClientRect() : null;

if (element_rect && args.checkRect &&
    (element_rect.width === 0 || element_rect.height === 0)) {
  elements = [];
  element = null;
  element_rect = null;
}

if (inset_probe) {
  bottom_inset = inset_probe.getBoundingClientRect().height;
  inset_probe.remove();
  window.__crossbench_inset_cache = {
    outerH: window.outerHeight,
    innerH: window.visualViewport.height,
    value: bottom_inset,
  };
}

const result = {
  count: elements.length,
  scrollTop:
      element ? (element === window ? window.scrollY : element.scrollTop) : 0,
  device_pixel_ratio: window.devicePixelRatio,
  window_outer_width: window.outerWidth,
  window_outer_height: window.outerHeight - bottom_inset,
  window_inner_width: window.visualViewport.width,
  window_inner_height: window.visualViewport.height,
  screen_width: screen.width,
  screen_height: screen.height,
  screen_avail_width: screen.availWidth,
  screen_avail_height: screen.availHeight,
  window_offset_x: screenX,
  window_offset_y: screenY,
  element_rect: element_rect ? {
    left: element_rect.left,
    top: element_rect.top,
    width: element_rect.width,
    height: element_rect.height,
  } :
                               null,
};

if (element) {
  if (args.click && element !== window) {
    element.click();
  }
  if (args.scrollTo !== undefined) {
    element.scrollTo({top: args.scrollTo, behavior: 'smooth'});
  }
}

return result;
