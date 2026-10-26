// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

function allocAnonymousHeap(sizeMB, randomRatio) {
  const PAGE_SIZE = 4096;
  const FLOAT64_BYTES = 8;
  const FLOAT64_PER_PAGE = PAGE_SIZE / FLOAT64_BYTES;
  const MB = 1024 * 1024;
  const totalCount = Math.floor((sizeMB * MB) / FLOAT64_BYTES);
  const randomCount = FLOAT64_PER_PAGE * randomRatio;

  // Using Float64Array as each element of Float64Array should consume 64
  // bits memory.
  const array = new Float64Array(totalCount);
  for (let i = 0; i < array.length; i++) {
    if (i % FLOAT64_PER_PAGE < randomCount) {
      array[i] = Math.random();
    } else {
      array[i] = 0.0;
    }
  }
  return array;
}

function createBmpBlobUrl(width, height, seed) {
  // 54-byte BMP header + 2 bytes padding for 4-byte alignment.
  const headerSize = 56;
  const rowBytes = width * 3;
  const pixelBytes = rowBytes * height;
  const fileSize = headerSize + pixelBytes;
  const buffer = new ArrayBuffer(fileSize);
  const view = new DataView(buffer);

  // BITMAPFILEHEADER (14 bytes)
  view.setUint8(0, 0x42);  // 'B'
  view.setUint8(1, 0x4d);  // 'M'
  view.setUint32(2, fileSize, true);
  view.setUint32(6, 0, true);
  view.setUint32(10, headerSize, true);

  // BITMAPINFOHEADER (40 bytes)
  view.setUint32(14, 40, true);
  view.setInt32(18, width, true);
  view.setInt32(22, height, true);
  view.setUint16(26, 1, true);
  view.setUint16(28, 24, true);  // 24-bit RGB
  view.setUint32(30, 0, true);   // BI_RGB
  view.setUint32(34, pixelBytes, true);
  view.setInt32(38, 2835, true);
  view.setInt32(42, 2835, true);
  view.setUint32(46, 0, true);
  view.setUint32(50, 0, true);

  const words = new Uint32Array(buffer, headerSize, Math.floor(pixelBytes / 4));
  let s = (seed * 2654435761) >>> 0;
  if (s === 0)
    s = 0x12345678;
  for (let i = 0; i < words.length; i++) {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    words[i] = s;
  }

  const blob = new Blob([buffer], {type: 'image/bmp'});
  return URL.createObjectURL(blob);
}

function populateDiscardableImages(imageCount, tabSeed) {
  const container = document.createElement('div');
  container.id = 'stress-discardable-container';
  container.style.display = 'flex';
  container.style.flexDirection = 'column';
  container.style.gap = '8px';

  const statusHeader = document.createElement('div');
  statusHeader.id = 'stress-status';
  container.appendChild(statusHeader);

  const imgs = [];
  for (let idx = 0; idx < imageCount; idx++) {
    const img = document.createElement('img');
    img.className = 'stress-discardable-img';
    img.width = 1024;
    img.height = 512;
    img.decoding = 'sync';
    img.loading = 'eager';
    const blobUrl = createBmpBlobUrl(1024, 512, (tabSeed + 1) * 100 + idx);
    img.src = blobUrl;
    img.decode()
        .then(() => {
          // Blink retains the encoded data (ParkableImage, possibly parked to
          // disk), so revoking only drops the blob: URL mapping and lets the
          // browser free its copy of the Blob.
          setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
        })
        .catch(() => {});
    // Keep <img> in the DOM so revisit_tab.js can decode/scroll to it again.
    // The decoded pixels live in cc's discardable image decode cache and may be
    // purged under memory pressure, idle timeouts, or when the tab is hidden.
    container.appendChild(img);
    imgs.push(img);
  }

  if (document.body.firstChild) {
    document.body.insertBefore(container, document.body.firstChild);
  } else {
    document.body.appendChild(container);
  }
  return imgs;
}

const pageLoadedTs = performance.now();

const allocMb = ALLOC_MB;
const imageCount = IMAGE_COUNT;
const tabSeed = parseInt('TAB_INDEX', 10) || 0;

const startTime = new Date();
const allocStartTs = performance.now();

// Assigns the content to document to avoid optimization of unused data.
document.out = allocAnonymousHeap(allocMb, 0.67);
document.stressImages = populateDiscardableImages(imageCount, tabSeed);

const allocEndTs = performance.now();
const elapsedSec = (new Date() - startTime) / 1000;

const statusEl = document.getElementById('stress-status');
if (statusEl) {
  statusEl.textContent =
      `Window WINDOW_INDEX | Tab TAB_INDEX | Allocated ${allocMb} MB heap + ` +
      `${imageCount} discardable images (~${imageCount * 2} MB RGBA) ` +
      `in ${elapsedSec.toFixed(3)}s`;
}

// Create the marks after the allocation to work around the issue where marks
// created too early after a process starts are dropped.
performance.mark('page-loaded~TAB_INDEX', {
  startTime: pageLoadedTs,
});
performance.mark('allocation-start~TAB_INDEX', {
  startTime: allocStartTs,
});
performance.mark('allocation-done~TAB_INDEX', {
  startTime: allocEndTs,
});
