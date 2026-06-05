# GCP — sudo hatası çözümü

Hata:
```
sudo: I'm sorry asilsoykan035. I'm afraid I can't do that
```

`asilsoykan035` kullanıcısının **sudo (root) yetkisi yok**. Bootstrap nginx/systemd kurmak için sudo gerekir.

---

## Çözüm A — GCP IAM (önerilen, 2 dk)

1. [Google Cloud Console](https://console.cloud.google.com) → **IAM & Admin** → **IAM**
2. Kendi Google hesabını bul → **Edit** (kalem)
3. **Add another role** → **Compute OS Admin Login** ekle → **Save**
4. VM’yi **durdur/başlat** gerekmez; 1–2 dk bekle
5. **Tarayıcı SSH** ile VM’e tekrar gir → dene:
   ```bash
   sudo whoami
   ```
   `root` dönmeli.

Sonra:
```bash
cd /opt/binancex/predmarket-scanner
sudo bash deploy/gcp_demo_bootstrap.sh
```

---

## Çözüm B — Tarayıcı SSH’tan sudo ver (IAM yetmezse)

GCP Console → VM → **SSH** (tarayıcı). Orada sudo çalışıyorsa:

```bash
echo 'asilsoykan035 ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/asilsoykan035
sudo chmod 440 /etc/sudoers.d/asilsoykan035
```

Mac SSH’tan tekrar:
```bash
sudo bash deploy/gcp_demo_bootstrap.sh
```

---

## Çözüm C — Sudo olmadan bot (geçici, panel tüneli)

Sudo alamıyorsan bot yine çalışır; panel Mac’ten tünel ile:

**Sunucuda (sudo yok):**
```bash
cd /opt/binancex/predmarket-scanner
bash deploy/gcp_demo_user_install.sh
```

**Mac’te panel:**
```bash
ssh -i ~/.ssh/id_ed25519 -L 9005:127.0.0.1:9005 asilsoykan035@34.104.243.96
```
Tarayıcı: http://127.0.0.1:9005/

---

## Passphrase her seferinde soruluyorsa

Mac’te bir kez:
```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```
Passphrase gir → oturum boyunca tekrar sormaz.

Veya GCP’ye passphrase’siz yeni key:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_gcp -N "" -C "asilsoykan035@gcp"
cat ~/.ssh/id_ed25519_gcp.pub
```
Metadata’ya: `asilsoykan035:ssh-ed25519 AAAA... asilsoykan035@gcp`
