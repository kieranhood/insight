# The Insight appliance

Insight is supplied as an appliance that **50N Systems owns and administers** (design D11). This page is how 50N builds and looks after each one.

## What the client does and does not get

Use this summary in client agreements.

| The client and crew get | The client and crew do not get |
|---|---|
| Insight's web interface, with crew and engineer accounts | Any operating-system, shell or Docker account on the appliance |
| The appliance installed and maintained by 50N | The software, image or disk contents; copying, modification and reverse engineering are prohibited (see `LICENSE`) |
| | The firmware password, disk recovery key or SSH keys |

The licence notice is shown on Insight's sign-in and About pages and is carried as a label on the image. **The contract's licence terms are the legal backstop.** The wording in `LICENSE` is a placeholder to be reviewed by 50N's legal advisers.

## Hardware

- A fanless x86 mini-PC (Intel N100 class, 8–16 GB RAM, SSD) **with TPM 2.0 and Secure Boot support**. Check both before buying.
- Mounted in the comms rack and powered from the UPS.

## 1. Firmware lock checklist

Do this before installing the OS, and record the firmware password in 50N's password manager under the appliance's serial number.

- [ ] Firmware (BIOS/UEFI) **administrator password** set
- [ ] **Secure Boot** enabled, standard keys
- [ ] **TPM 2.0** enabled
- [ ] **USB boot and network (PXE) boot disabled**
- [ ] **Boot order locked** to the internal disk
- [ ] Wake on power restore: **power on** (so the appliance restarts after a power cut)

Check: with a bootable USB stick inserted, the appliance still boots from its disk, and the firmware setup asks for the password.

## 2. Install Debian with full-disk encryption

1. Install **Debian stable**. In the installer, choose **guided partitioning with encrypted LVM** (LUKS2), with a strong temporary passphrase.
2. Create the user `50n-admin` (temporary password; the playbook locks it).
3. Install only *SSH server* and *standard system utilities*.

## 3. Enrol the disk key in the TPM

This lets the appliance unlock itself at boot, so it restarts unattended after a power cut, while the disk stays unreadable if it is removed.

```bash
sudo systemd-cryptenroll --recovery-key /dev/<luks partition>
```

**Record the printed recovery key in 50N's password manager** under the appliance's serial number. It is the only way in if the TPM unlock ever fails.

```bash
sudo systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks partition>
```

```bash
sudo systemd-cryptenroll --wipe-slot=password /dev/<luks partition>
```

Then add `tpm2-device=auto` to the partition's line in `/etc/crypttab` and rebuild the initramfs:

```bash
sudo update-initramfs -u
```

Binding to PCR 7 (the Secure Boot policy) survives most firmware and kernel updates. Check by rebooting and confirming no passphrase is asked for.

## 4. Provision with the playbook

From a 50N laptop, copy `appliance/inventory.example.ini` and `appliance/appliance-vars.example.yml`, fill in the address, your team's SSH public keys and the on-board time source, then run:

```bash
ansible-playbook -i inventory.ini appliance/provision.yml -e @appliance-vars.yml
```

The playbook:

- installs Docker, chrony and unattended security upgrades;
- makes `50n-admin` the only account in the `docker` group (Docker access amounts to root);
- locks the root and `50n-admin` passwords;
- sets SSH to key-only, with no root sign-in, `50n-admin` only and 50N's keys only;
- installs `compose.yaml` and the image tag in `/opt/insight`.

## 5. Check the appliance before it leaves the workshop

- [ ] `ssh` with a password is refused, for every account, including root
- [ ] `ssh -i <50N key> 50n-admin@<appliance>` works
- [ ] `getent group docker` lists only `50n-admin`
- [ ] Rebooting needs no passphrase
- [ ] With the disk removed and attached to another computer, it can't be read without the recovery key
- [ ] Insight starts (`docker compose up -d`) and reports healthy

## Keys and passwords: who holds what

| Secret | Held by | Where |
|---|---|---|
| SSH private keys | Each 50N engineer | Their own machine. Public keys are listed in the playbook vars |
| Firmware password | 50N | Password manager, per appliance |
| Disk recovery key | 50N | Password manager, per appliance |
| Insight engineer accounts | 50N engineers, and the ETO if agreed | Insight itself |

## Firmware and OS updates

- **OS security updates** install automatically.
- **Firmware (BIOS) updates** are done by 50N only, with the recovery key to hand: a firmware update can change the TPM measurements so that the disk asks for the recovery key once. After entering it, re-enrol:

  ```bash
  sudo systemd-cryptenroll --wipe-slot=tpm2 --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks partition>
  ```

- If crew ever have to type the recovery key in an emergency, **rotate it afterwards** (`systemd-cryptenroll --recovery-key`, then remove the old one) and update the password manager.

## Removing a key or an engineer

Remove their public key from the vars file and re-run the playbook. Its key list is exclusive, so removed keys stop working.
