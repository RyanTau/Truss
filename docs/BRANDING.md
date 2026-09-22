# Truss icon

The transparent cyan-to-violet thought bubble contains five white waveform bars. The same artwork is used for light and dark themes.

| Location | Support |
| --- | --- |
| GitHub README and HACS repository detail README | The README links directly to the published icon. `render_readme` is enabled in `hacs.json`. |
| Companion app/add-on store and installed app | `truss_engine/icon.png` and `logo.png` supply the Supervisor artwork. Refresh the store's repository information to pick up version 0.1.3. |
| Downloaded integration, HA 2026.3+ | PNGs in `custom_components/truss/brand/` provide local integration icons and logos. Update/redownload Truss and restart HA. |
| Downloaded integration, HA 2026.1 or 2026.2 | These versions cannot use bundled custom-integration brand images. They can still run Truss, but the integration tile may show a placeholder. |
| HACS listing/downloaded-repositories tile | HACS has an open issue with bundled custom brand icons. Including a root `icon.png` or README image does not override its tile's external image source. This display cannot be guaranteed by a Truss repository change. |

Home Assistant documents local custom-integration branding as available from [2026.3](https://developers.home-assistant.io/docs/core/integration/brand_images/). The old shared-brand route is unavailable for new custom integrations: the [brands submission template](https://github.com/home-assistant/brands/blob/master/.github/PULL_REQUEST_TEMPLATE.md) explicitly says those submissions are no longer accepted. The HACS limitation is tracked in [hacs/integration#5223](https://github.com/hacs/integration/issues/5223).

The minimum Home Assistant version remains **2026.1.0**. No frontend patch, external brand registration, or HACS modification is installed by Truss.

## Assets and reproduction

- `assets/truss-icon-source.png`: original generated artwork with transparency.
- `icon.png`: repository/README icon, 256 px.
- `custom_components/truss/brand/`: 256 px and 512 px icon/logo files, including dark variants.
- `truss_engine/icon.png`: 128 px app icon; `logo.png`: 256 px app logo.

On Windows, run `powershell -NoProfile -File scripts/build_brand.ps1` to trim transparent excess and export the PNG sizes using System.Drawing. It preserves alpha and changes only framing and resolution. The manual installation ZIP includes the integration's brand directory.

The artwork was created with the built-in image generation tool using this prompt:

> Use case: logo-brand. Create a polished standalone app icon for Truss, a voice-controlled smart home integration. Primary request: a cool thought bubble with a sound wave inside it. Clean bold thought-cloud silhouette with two small detached thought dots, containing a crisp five-bar audio waveform with rounded ends. Modern, confident, minimal, memorable; simple strong geometry, balanced square composition, reads clearly at 32 pixels. No letters, no text, no watermark, no mockup or surrounding UI. Use a genuinely transparent background, not a checkerboard painted into the image. Keep the entire symbol within the canvas with a small even safety margin. The wave must contrast strongly against the bubble and the icon must work in both light and dark app themes. One finished icon, square PNG.
