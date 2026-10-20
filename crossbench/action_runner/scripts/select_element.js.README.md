# `select_element.js`

This script locates DOM elements (by CSS selector or `xpath/...` prefix) and
performs element queries, interactions, or viewport geometry measurements in a
single synchronous WebDriver `executeScript` round-trip.

## Execution & Arguments

`ActionRunner` evaluates `select_element.js` with a single options object in
`arguments[0]`:

* `selector` (`string | null | undefined`): The selector string (supports
  `xpath/...` or CSS selectors). When omitted/falsy, defaults to `window`.
* `scrollIntoView` (`boolean`): Whether to scroll the matched `element` into
  view (`element.scrollIntoView({block: 'nearest'})`).
* `checkRect` (`boolean`): When `true`, treats the element as not found
  (`count: 0`) if its bounding client rect has zero width or height.
* `click` (`boolean`): When `true`, calls `element.click()`.
* `scrollTo` (`number | undefined`): When defined, calls
  `element.scrollTo({top: scrollTo, behavior: 'smooth'})`.

## Return Value

Always returns a dictionary object containing:

* `count` (`number`): Number of matched elements (`0` if none matched or if
  `checkRect` failed, `1` when `selector` is omitted).
* `scrollTop` (`number`): Current vertical scroll offset of the matched element
  (or `window.scrollY` when `selector` is omitted).
* Viewport & element geometry fields (matching `ViewportInfo.__init__`
  parameters):
  * `device_pixel_ratio` (`number`)
  * `window_outer_width` (`number`)
  * `window_outer_height` (`number`, adjusted for unconsumed bottom inset)
  * `window_inner_width` (`number`)
  * `window_inner_height` (`number`)
  * `screen_width` (`number`)
  * `screen_height` (`number`)
  * `screen_avail_width` (`number`)
  * `screen_avail_height` (`number`)
  * `window_offset_x` (`number`)
  * `window_offset_y` (`number`)
  * `element_rect` (`{left, top, width, height} | null`)

## Edge-to-Edge Mobile Bottom Inset Compensation

To convert CSS viewport coordinates into physical display coordinates,
`ViewportInfo` computes the height of the top browser UI chrome (address bar,
tab strip, status bar) from `window_outer_height - window_inner_height`.

On edge-to-edge mobile displays (such as Android 15+), a fullscreen browser
window reports `window.screenY === 0` and `window.outerHeight === screen.height`
(spanning the entire display, including the bottom system navigation/gesture bar
region). However, `window.visualViewport.height` excludes the bottom system bar
unless the page actively extends into the unsafe area:

* `env(safe-area-max-inset-bottom)` reports the height of the bottom system bar
  region included in `window.outerHeight`.
* `env(safe-area-inset-bottom)` reports the portion of that bottom region
  currently overlapped by the viewport (`window.visualViewport.height`).

The difference (`safe-area-max-inset-bottom - safe-area-inset-bottom`) is the
portion of `window.outerHeight` occupied by the bottom system bar rather than
top browser chrome.

### Probe Element & Layout Batching

Because CSS environment variables (`env(...)`) cannot be read directly from
JavaScript without evaluating CSS on an element:

1. When `window.screenY === 0 && window.outerHeight === screen.height`, the
   script checks `window.__crossbench_inset_cache` for a cached measurement
   matching the current `(window.outerHeight, window.visualViewport.height)`.
2. On a cache miss, it attaches a hidden, zero-width `<div>` (`inset_probe`)
   with:
   ```css
   height: calc(
     env(safe-area-max-inset-bottom, 0px) - env(safe-area-inset-bottom, 0px)
   );
   ```
3. To avoid triggering an extra synchronous layout reflow, the probe element's
   `getBoundingClientRect().height` is read **after** optional
   `element.scrollIntoView(...)` and `element.getBoundingClientRect()`, the
   probe is immediately removed from the DOM (`inset_probe.remove()`), and the
   result is stored in `window.__crossbench_inset_cache`.
4. `window_outer_height` is returned as `window.outerHeight - bottom_inset` so
   that `window_outer_height - window_inner_height` reflects only top browser
   chrome.
