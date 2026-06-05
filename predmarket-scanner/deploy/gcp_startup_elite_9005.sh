#!/bin/bash
# GCE startup — elite-9005-data disk mount
set -e
DATA_DEV=/dev/disk/by-id/google-elite-9005-data
MNT=/opt/binancex/data
if [[ -b "$DATA_DEV" ]] && ! mountpoint -q "$MNT"; then
  mkdir -p "$MNT"
  if ! blkid "$DATA_DEV" | grep -q ext4; then
    mkfs.ext4 -F "$DATA_DEV"
  fi
  if ! grep -q elite-9005-data /etc/fstab; then
    echo "$DATA_DEV $MNT ext4 defaults 0 2" >> /etc/fstab
  fi
  mount -a
  chown -R ubuntu:ubuntu "$MNT" 2>/dev/null || true
fi
