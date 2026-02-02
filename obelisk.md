# Obelisk Server Runbook

## Overview

| Property | Value |
|----------|-------|
| Hostname | obelisk |
| CPU | Intel i7-6850K |
| RAM | 32GB |
| GPU | NVIDIA 3080 Ti |
| Storage | 100GB root (NVMe), 1.7TB /data (NVMe), 500GB SSD (unused) |
| WiFi | Broadcom BCM4352 (broadcom-wl-dkms) |
| Location | Closet |
| Access | Tailscale SSH, GLKVM emergency |

## Normal Operations

### SSH Access
```bash
ssh nik@obelisk
```

### Check System Status
```bash
# System resources
htop
nvidia-smi

# Disk usage
df -h

# Service status
systemctl status tailscaled
systemctl status NetworkManager
systemctl status sshd

# Recent logs
journalctl -b --no-pager | tail -100
```

### Reboot
```bash
sudo reboot
```

### Shutdown
```bash
sudo shutdown now
```

### System Updates
```bash
sudo pacman -Syu
yay -Syu  # includes AUR packages
```

After kernel or nvidia updates, reboot.

---

## Troubleshooting

### Server Unreachable via Tailscale

1. **Ping local IP** (if on same network): obelisk
   - If reachable: Tailscale issue
   - If unreachable: Server or WiFi issue

2. **Check via GLKVM** — connect and log in

3. **Check Tailscale**:
   ```bash
   sudo systemctl status tailscaled
   sudo tailscale status
   sudo systemctl restart tailscaled
   ```

4. **Check network**:
   ```bash
   ip addr
   nmcli device status
   ping google.com
   ```

### WiFi Not Connecting

1. Check interface exists:
   ```bash
   ip link show wlan0
   ```

2. If missing, reload driver:
   ```bash
   sudo modprobe -r wl
   sudo modprobe wl
   ```

3. Check NetworkManager:
   ```bash
   nmcli device status
   nmcli connection show
   sudo systemctl restart NetworkManager
   ```

4. Manually connect:
   ```bash
   nmcli device wifi list
   nmcli device wifi connect "SpideyNET" password "YOURPASSWORD"
   ```

5. If driver missing after kernel update:
   ```bash
   yay -S broadcom-wl-dkms
   sudo reboot
   ```

### Server Won't Boot

1. Connect via GLKVM
2. Watch boot messages for errors
3. If kernel panic or can't find root:
   - Boot from Arch USB
   - Mount and chroot:
     ```bash
     mount /dev/nvme0n1p2 /mnt
     mount /dev/nvme0n1p1 /mnt/boot
     mount /dev/nvme0n1p3 /mnt/data
     arch-chroot /mnt
     ```
   - Fix bootloader or fstab issues

### NVIDIA Driver Issues

1. Check driver loaded:
   ```bash
   lsmod | grep nvidia
   nvidia-smi
   ```

2. If not loaded:
   ```bash
   sudo modprobe nvidia
   ```

3. Reinstall drivers:
   ```bash
   sudo pacman -S nvidia-open nvidia-utils cuda cudnn
   sudo reboot
   ```

### Disk Full

1. Check what's using space:
   ```bash
   sudo du -sh /* 2>/dev/null | sort -h
   sudo du -sh /data/* 2>/dev/null | sort -h
   ```

2. Clear pacman cache:
   ```bash
   sudo pacman -Sc
   ```

3. Clear old journal logs:
   ```bash
   sudo journalctl --vacuum-time=7d
   ```

---

## Emergency Recovery via GLKVM

### Access
1. Open GLKVM web interface
2. Connect to obelisk
3. Use virtual keyboard for special keys (F11, Del, etc.)

### Boot into BIOS
1. Reboot server
2. Send F2 or Del via GLKVM virtual keyboard

### Boot from USB
1. Insert Arch USB
2. Reboot
3. Send F11 via GLKVM for boot menu
4. Select USB drive

### Chroot Recovery
```bash
# From Arch live USB
mount /dev/nvme0n1p2 /mnt
mount /dev/nvme0n1p1 /mnt/boot
mount /dev/nvme0n1p3 /mnt/data
arch-chroot /mnt

# Now you can fix things
# After fixing:
exit
umount -R /mnt
reboot
```

### Reset User Password
```bash
# From chroot
passwd nik
```

---

## Service Management

### Docker (when configured)
Docker data lives on `/data/docker`.

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

Config location: `/etc/docker/daemon.json`
```json
{
  "data-root": "/data/docker"
}
```

### Tailscale
```bash
sudo systemctl status tailscaled
sudo tailscale status
sudo tailscale up    # re-authenticate
sudo tailscale down  # disconnect
```

### SSH
```bash
sudo systemctl status sshd
sudo systemctl restart sshd
```

Config: `/etc/ssh/sshd_config`

---

## Storage Layout

| Device | Mount | Size | Purpose |
|--------|-------|------|---------|
| nvme0n1p1 | /boot | 512MB | EFI, bootloader |
| nvme0n1p2 | / | 100GB | OS, packages |
| nvme0n1p3 | /data | 1.7TB | Models, docker, projects |
| sda | (unused) | 500GB | Available for /srv/assets |

### Mount the SSD (when ready)
```bash
# Format
sudo mkfs.ext4 /dev/sda

# Create mount point
sudo mkdir /srv/assets

# Add to fstab
echo "UUID=$(sudo blkid -s UUID -o value /dev/sda) /srv/assets ext4 rw,relatime 0 2" | sudo tee -a /etc/fstab

# Mount
sudo mount -a
```

---

## Key File Locations

| Path | Purpose |
|------|---------|
| /etc/NetworkManager/system-connections/home.nmconnection | WiFi credentials |
| /etc/ssh/sshd_config | SSH server config |
| /boot/loader/entries/arch.conf | Boot entry |
| /data | Large files, models, docker |

---

## Quick Reference

| Task | Command |
|------|---------|
| SSH in | `ssh nik@obelisk` |
| Check GPU | `nvidia-smi` |
| Check disk | `df -h` |
| Check services | `systemctl status tailscaled sshd NetworkManager` |
| Update system | `sudo pacman -Syu && yay -Syu` |
| View logs | `journalctl -b -f` |
| Restart network | `sudo systemctl restart NetworkManager` |
| Restart Tailscale | `sudo systemctl restart tailscaled` |
