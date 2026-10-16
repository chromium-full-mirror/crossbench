# `get_window_positions.js`

This script queries viewport, screen, window, and target DOM element geometry in
a single synchronous WebDriver `executeScript` round-trip so that `ActionRunner`
can translate CSS viewport coordinates into physical device screen coordinates.

## Execution & Arguments

When locating a DOM element, `ActionRunner._get_viewport_info()` prepends the
selector lookup snippet produced by `ActionRunner.get_selector_script()` (which
resolves `arguments[0]` and binds the matched node to `element`) before
evaluating `get_window_positions.js`.

The script receives two WebDriver arguments:

* `arguments[0]` (`string | null`): The selector string (or `null` when querying
  viewport geometry without a target element).
* `arguments[1]` (`boolean`): Whether to scroll the matched `element` into view
  (`element.scrollIntoView({block: 'nearest'})`) before measuring its bounding
  client rect.

## Edge-to-Edge Mobile Bottom Inset Compensation

To convert CSS viewport coordinates into physical display coordinates,
`ViewportInfo` computes the height of the top browser UI chrome (address bar,
tab strip, status bar) from `outer_height - inner_height`.

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
4. `outer_height` is returned as `window.outerHeight - bottom_inset` so that
   `outer_height - inner_height` reflects only top browser chrome.

## Return Value

Returns a 16-element array unpacking into `WindowPositions`:

1. `found_element` (`boolean`)
2. `window.devicePixelRatio` (`number`)
3. `window.outerWidth` (`number`)
4. `outer_height` (`number`, adjusted for unconsumed bottom inset)
5. `window.visualViewport.width` (`number`)
6. `window.visualViewport.height` (`number`)
7. `screen.width` (`number`)
8. `screen.height` (`number`)
9. `screen.availWidth` (`number`)
10. `screen.availHeight` (`number`)
11. `screenX` (`number`)
12. `screenY` (`number`)
13. `element_rect.left` (`number`)
14. `element_rect.top` (`number`)
15. `element_rect.width` (`number`)
16. `element_rect.height` (`number`)
