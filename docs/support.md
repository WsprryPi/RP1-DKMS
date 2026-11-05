<!-- SPDX-License-Identifier: MIT -->

# Get support

For WsprryPi installation, web interface, scheduling and application setup,
start with [WsprryPi support](https://wsprry-pi.readthedocs.io/en/devel/Support/index.html).
For a confirmed module, provider packaging or route-management problem, use
[RP1-GPCLK-DKMS issues](https://github.com/WsprryPi/RP1-DKMS/issues).
If the cause is unclear, describe the failing action and its message in the
WsprryPi support request.

## Include enough context

- Raspberry Pi model, operating-system release and running kernel;
- WsprryPi version and provider release or exact development source;
- selected GPIO and physical header connection;
- requested and active routes, if available;
- the action that failed, the exact error and its exit code;
- whether transmission is stopped and output state is confirmed; and
- recent installation, update, reboot or wiring changes.

Do not run a test transmission just to gather these details. Missing or
inaccessible information should be reported as such.

## Collect and review a support bundle

When WsprryPi is available:

1. Open **Maintenance > Support Bundle** and choose **Start support bundle**.
2. Associate it with an existing issue, choose to create an issue later, or
   choose **I am not using GitHub**. Supply the requested description/contact
   details for the private bundle record.
3. Leave **Actively probe I²C bus 1** cleared unless support specifically
   requests it. Choose **Create readable candidate**.
4. Wait for collection to finish. Record the case ID, choose
   **Download readable candidate**, and open that archive with your computer's
   archive viewer. Read its `bundle/README.txt`, configuration and logs before
   approving sharing. A failed download can be retried while the candidate is
   retained on the Pi.
5. If you approve those exact bytes, follow the panel's explicit encryption
   and private-upload steps. Record the case ID and the upload result for the
   support request. Creating, downloading or encrypting the bundle does not
   itself upload it, create an issue or notify the maintainer.

The bundle includes RP1 kernel/header and DKMS observations, module metadata,
endpoint/socket state, route-journal inventory and the runtime provider's passive
inspection when available. Collection does not repair the system or authorize
output. Unavailable observations remain visible in the report.

Download and inspect the readable archive before sharing. It can contain
callsigns, hostnames, addresses, paths, configuration and logs; automatic
redaction is best-effort. Follow the application's review/encryption and private
upload workflow rather than attaching the readable archive to a public issue.
Creating a bundle does not upload it automatically.

The readable candidate is retained on the Pi for review/encryption and expires
after 24 hours unless deleted earlier. Download it before relying on it as
your retained report. **Delete from Pi** removes the retained candidate, not
your downloaded copy. Keep case IDs and any private upload references out of
unrelated public logs or screenshots.

For exact controls and retention behavior, see
[WsprryPi's support bundle guide](https://wsprry-pi.readthedocs.io/en/devel/User_Interface/Maintenance/support_bundle.html).
If the application is unavailable, retain the bounded results from the
[command-line reference](command-line.md) and review them before sharing.
