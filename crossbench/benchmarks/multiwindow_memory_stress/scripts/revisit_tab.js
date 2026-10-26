// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// The 'tab-revisit-start~PHASE~TAB_INDEX' mark is created before this script
// runs, for the 'cycle' phase in the previous tab before switching to this tab.

// Resolves on the next animation frame, or after |ms| if rAF is throttled.
function nextFrame(ms = 100) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    requestAnimationFrame(() => {
      clearTimeout(timer);
      resolve();
    });
  });
}

// Touch one element per 4 KiB page so swapped-out pages are faulted back in.
let checksum = 0.0;
if (document.out && document.out.length) {
  const stride = 512;  // 4096 / 8
  for (let i = 0; i < document.out.length; i += stride) {
    checksum += document.out[i];
  }
  document.out[0] = checksum;
}

// Decode and scroll each image into view to trigger image decode cache locking
// and re-decoding if evicted.
const imgs = Array.from(document.querySelectorAll('.stress-discardable-img'));
let decodeFailures = 0;
await Promise.all(imgs.map((img) => img.decode().catch(() => {
  decodeFailures++;
})));

for (const img of imgs) {
  img.style.transform =
      img.style.transform === 'scale(0.999)' ? 'scale(1)' : 'scale(0.999)';
  img.scrollIntoView({behavior: 'instant', block: 'center'});
  await nextFrame();
  await nextFrame();
}
window.scrollTo(0, 0);
await nextFrame();

const revisitEndTs = performance.now();
performance.mark('tab-revisit-done~PHASE~TAB_INDEX', {
  startTime: revisitEndTs,
  detail: {images: imgs.length, decodeFailures: decodeFailures},
});
