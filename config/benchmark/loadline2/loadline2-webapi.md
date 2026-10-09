# LoadLine 2 WebAPI Benchmark

LoadLine 2 WebAPI is a modification of the [LoadLine 2 benchmark](README.md)
that doesn't use any Chrome- or Android-specific features, relying instead on
pure WebAPI. This makes it possible to run the benchmark on e.g. iOS devices,
but the setup is a little bit more complicated.

*** note
Note: LoadLine 2 WebAPI scores are not directly comparable to LoadLine 2 scores!
When comparing devices, make sure you run the same modification of LoadLine on
all of them.
***

## Network setup

Page loading speed heavily depends on the network latency, so making the
network connection as predictable as possible is crucial to getting
consistent results. We recommend using Ethernet connection to the device,
because it provides stable network latency. While it's possible to run the
benchmark via WiFi, the noise level will likely be so high that you won't be
able to make any meaningful conclusions. The following instructions assume you
use Ethernet connection.

## Prerequisites (one-off setup)

* Obtain accessories required to connect the device to your host via Ethernet.
  Usually, it's two USBC<->Ethernet adaptors and an Ethernet cable, but your
  setup may vary.

* Configure Safari remote automation on the iPhone
  * Settings > Apps > Safari > Advanced, then Turn on Web Inspector and Remote
    Automation
  * Open Safari in the Mac and in the iPhone. In the Mac, Develop > Iphone >
    Connect via network.

    After clicking "Connect Via Network", open the menu again and verify the
    option is ticked. If it's not, you might need to set up a password on your
    iPhone and retry.
  * Increase Auto-lock time as much as possible in settings

* Install custom certificates on the device.
  * Upload `third_party/webpagereplay/ecdsa_cert.pem` file to the device.
  * On iOS
    * Files > Select your file. This will show “Profile downloaded. Review the
      profile in the settings app”.
    * Then go to Settings > More for your iPhone > Profile downloaded > View
      Profile > Install > Install
    * Then go to Settings > General > About > Certificate Trust Settings > Turn
      on Test CA
  * On Android (depends on the OEM actually, but typically looks somewhat like
    this):
    * Settings > Security and privacy > CA certificate > CA certificate >
      Install anyway > Select your file

* Install required packages on the host and add `dnsmasq` to PATH
  * E.g. on Mac:
    `brew install go dnsmasq && export PATH=$PATH:/opt/homebrew/opt/dnsmasq/sbin`

## Running the benchmark

* Make sure you only have 1 device connected to the host.
* Determine the name of the interface the device will be connected to.
  * If you are using a USBC<->Ethernet adaptor, a simple way to determine the
    interface name is to disconnect/reconnect the adaptor and run `ifconfig`
    to see which interface disappears.
* Run `./cb.py setup_cross_platform_mode --interface <interface>`, it will guide
  you through the network setup process (requires root on the host). Keep it
  running in a separate terminal window for the entire benchmark run.
* Run `./cb.py loadline2-webapi-phone --browser <browser>`, where browser can
  be one of `android:chrome` or `ios:safari`. This command also requires root on
  the host. Alternatively, you can run the tablet version with
  `./cb.py loadline2-webapi-tablet --browser <browser>`.
