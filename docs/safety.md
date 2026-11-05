<!-- SPDX-License-Identifier: MIT -->

# RF and electrical precautions

The GPIO output is a clock signal. It needs suitable filtering and an RF
interface before connection to an antenna or other equipment. Its harmonics,
level and impedance must be considered as part of the complete transmitter.
Software installation and a healthy status report do not qualify that RF path.

## Before enabling output

- Confirm that you are authorized to transmit on the intended frequency and
  mode, and follow local amateur radio requirements.
- Check the band, mode and hardware limits in your WsprryPi version's manual.
- Use appropriate filtering, isolation, loading and attenuation for the actual
  equipment. Protect receivers and test instruments from excessive input.
- Verify the physical header connection against the selected GPIO number.
  Stop output and make the hardware safe before changing wiring; power down
  before handling header connections.
- Ensure no other software or enabled GPIO role is using the selected pin,
  clock or DMA resources. Operator responsibility does not create technical
  isolation from another root process or direct hardware access.

On a standard Raspberry Pi 40-pin header, the two supported routes are
**GPIO4, physical pin 7**, and **GPIO20, physical pin 38**. GPIO numbering and
physical pin numbering are different. Confirm the connector orientation and
ground connection using your board and RF-interface documentation. A Compute
Module carrier or custom connector needs its own verified mapping; do not
assume its connector positions match the standard header. Selecting a route
does not move a cable attached to the other.

Turn [scheduled transmission off and finish or cancel active work](getting-started.md#make-the-transmitter-idle)
before changing a route. A browser disconnect is not an emergency stop, and
turning the scheduling switch off alone does not cancel committed work.

## Stop when state is uncertain

Wait for cancellation and cleanup to finish before route changes or maintenance.
An unknown output observation is not proof that output is off. A cleanup fault,
active owner, pending transaction or unexplained route mismatch requires
investigation before further operation.

Do not clear a fault by deleting ownership records, forcing module removal or
adding another overlay. Use [maintenance and recovery](maintenance.md) and
preserve the diagnostic details. If output cannot be confirmed safe, make the
physical RF setup safe before continuing investigation.

For station-level filtering, calibration and electrical design guidance, see
[WsprryPi RF and electrical considerations](https://wsprry-pi.readthedocs.io/en/devel/Advanced_Operations/rf_electrical.html).
