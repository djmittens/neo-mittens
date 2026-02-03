#!/usr/bin/env bash
# System-level configuration installer for obelisk server
# This sets up the data partition bind mounts for /home, /var/log, and /var/cache

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"

echo "=== System Configuration Installer ==="
echo ""
echo "This script will configure bind mounts to use the large data partition"
echo "for /home, /var/log, and /var/cache directories."
echo ""
echo "PREREQUISITES:"
echo "  - Root/sudo access required"
echo "  - Large data partition already mounted at /data"
echo "  - Partition UUID: 624b0d97-3fc0-4fbd-a9f0-d9e327cc6303"
echo ""

# Check if data partition is mounted
if ! mount | grep -q "/data"; then
  echo "ERROR: /data partition not mounted!"
  echo "Please ensure the data partition is properly mounted first."
  exit 1
fi

# Check if we're running as root or have sudo
if [ "$EUID" -ne 0 ]; then 
  if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: This script requires root access and sudo is not available."
    exit 1
  fi
  SUDO="sudo"
else
  SUDO=""
fi

echo "Step 1: Creating directories on data partition..."
$SUDO mkdir -p /data/home /data/var/log /data/var/cache
echo "✓ Directories created"
echo ""

echo "Step 2: Checking if data needs to be migrated..."
HOME_SIZE=$($SUDO du -sh /home 2>/dev/null | cut -f1 || echo "0")
LOG_SIZE=$($SUDO du -sh /var/log 2>/dev/null | cut -f1 || echo "0")
CACHE_SIZE=$($SUDO du -sh /var/cache 2>/dev/null | cut -f1 || echo "0")

echo "  /home:      $HOME_SIZE"
echo "  /var/log:   $LOG_SIZE"
echo "  /var/cache: $CACHE_SIZE"
echo ""

# Check if directories are already mounted
if mount | grep -q "on /home type"; then
  echo "⚠ /home is already mounted - skipping data copy"
  SKIP_HOME=1
else
  SKIP_HOME=0
fi

if mount | grep -q "on /var/log type"; then
  echo "⚠ /var/log is already mounted - skipping data copy"
  SKIP_LOG=1
else
  SKIP_LOG=0
fi

if mount | grep -q "on /var/cache type"; then
  echo "⚠ /var/cache is already mounted - skipping data copy"
  SKIP_CACHE=1
else
  SKIP_CACHE=0
fi

# Copy data if not already mounted
if [ $SKIP_HOME -eq 0 ]; then
  echo "Step 3a: Copying /home to /data/home (this may take a while)..."
  $SUDO rsync -avxHAX /home/ /data/home/
  echo "✓ Home directory copied"
else
  echo "Step 3a: Skipping /home copy (already mounted)"
fi
echo ""

if [ $SKIP_LOG -eq 0 ]; then
  echo "Step 3b: Copying /var/log to /data/var/log..."
  $SUDO rsync -avxHAX /var/log/ /data/var/log/
  echo "✓ Log directory copied"
else
  echo "Step 3b: Skipping /var/log copy (already mounted)"
fi
echo ""

if [ $SKIP_CACHE -eq 0 ]; then
  echo "Step 3c: Copying /var/cache to /data/var/cache..."
  $SUDO rsync -avxHAX /var/cache/ /data/var/cache/
  echo "✓ Cache directory copied"
else
  echo "Step 3c: Skipping /var/cache copy (already mounted)"
fi
echo ""

echo "Step 4: Updating /etc/fstab..."
# Backup fstab
$SUDO cp /etc/fstab /etc/fstab.backup.$(date +%Y%m%d-%H%M%S)

# Check if our bind mounts are already in fstab
if grep -q "# Bind mounts to use large data partition" /etc/fstab; then
  echo "⚠ Bind mounts already present in /etc/fstab - skipping"
else
  # Append bind mounts to fstab
  echo "" | $SUDO tee -a /etc/fstab >/dev/null
  echo "# Bind mounts to use large data partition" | $SUDO tee -a /etc/fstab >/dev/null
  echo "/data/home     /home       none    bind    0 0" | $SUDO tee -a /etc/fstab >/dev/null
  echo "/data/var/log  /var/log    none    bind    0 0" | $SUDO tee -a /etc/fstab >/dev/null
  echo "/data/var/cache  /var/cache  none    bind    0 0" | $SUDO tee -a /etc/fstab >/dev/null
  echo "✓ Bind mounts added to /etc/fstab"
fi
echo ""

echo "Step 5: Mounting bind mounts..."
if [ $SKIP_HOME -eq 0 ]; then
  $SUDO mount /home && echo "✓ Mounted /home" || echo "⚠ /home already mounted"
fi
if [ $SKIP_LOG -eq 0 ]; then
  $SUDO mount /var/log && echo "✓ Mounted /var/log" || echo "⚠ /var/log already mounted"
fi
if [ $SKIP_CACHE -eq 0 ]; then
  $SUDO mount /var/cache && echo "✓ Mounted /var/cache" || echo "⚠ /var/cache already mounted"
fi
echo ""

echo "Step 6: Verifying mounts..."
mount | grep -E '(/home|/var/log|/var/cache)' || echo "⚠ No bind mounts found!"
echo ""

echo "Step 7: Cleaning up old files on root filesystem..."
echo "WARNING: This will delete old files that are now hidden by bind mounts."
read -p "Proceed with cleanup? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Mount root filesystem to temporary location to access hidden files
  $SUDO mkdir -p /mnt/root
  $SUDO mount --bind / /mnt/root
  
  echo "Checking sizes of old files..."
  $SUDO du -sh /mnt/root/home 2>/dev/null || echo "  /mnt/root/home: already clean"
  $SUDO du -sh /mnt/root/var/log 2>/dev/null || echo "  /mnt/root/var/log: already clean"
  $SUDO du -sh /mnt/root/var/cache 2>/dev/null || echo "  /mnt/root/var/cache: already clean"
  
  echo "Removing old files..."
  $SUDO rm -rf /mnt/root/home/* 2>/dev/null && echo "✓ Cleaned /home" || echo "⚠ /home already clean"
  $SUDO rm -rf /mnt/root/var/log/* 2>/dev/null && echo "✓ Cleaned /var/log" || echo "⚠ /var/log already clean"
  $SUDO rm -rf /mnt/root/var/cache/* 2>/dev/null && echo "✓ Cleaned /var/cache" || echo "⚠ /var/cache already clean"
  
  $SUDO umount /mnt/root
  $SUDO rmdir /mnt/root
  echo "✓ Cleanup complete"
else
  echo "⚠ Skipped cleanup - you can run it manually later"
fi
echo ""

echo "=== Installation Complete ==="
echo ""
echo "Root filesystem usage:"
df -h /
echo ""
echo "Data partition usage:"
df -h /data
echo ""
echo "Mount status:"
mount | grep -E '(/home|/var/log|/var/cache)'
echo ""
echo "These mounts will persist across reboots (configured in /etc/fstab)."
echo ""
