# Home Assistant brands assets

Home Assistant does not read images from an integration's repository. The
frontend resolves them by domain from `brands.home-assistant.io`, so these
files do nothing until they are submitted to
[home-assistant/brands](https://github.com/home-assistant/brands) as:

    custom_integrations/epson_projector_serial/
        icon.png       256x256
        icon@2x.png    512x512
        logo.png       512x115   (max 512 wide, 256 tall)
        logo@2x.png    1024x230

Until then `brands.home-assistant.io/_/epson_projector_serial/icon.png`
returns an "icon not available" placeholder, which is what shows in
**Settings → Devices & services**.

Made from Epson's wordmark: trimmed to the mark, then resized in
premultiplied alpha so the edges do not pick up a halo. The icons are the
wordmark centred on a transparent square, which is how Home Assistant's own
`epson` brand entry handles it — Epson has no separate symbol.

Epson is a trademark of Seiko Epson Corporation.
