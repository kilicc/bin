# GCP SSH — Permission denied (publickey) çözümü

## Neden `ubuntu@34.104.243.96` çalışmıyor?

GCP’ye eklediğin key’in sonundaki e-mail **`rushpaybusiness@gmail.com`** → kullanıcı adı **`rushpaybusiness`** olur, **`ubuntu` değil**.

---

## Adım 1 — Key’i doğru formatta GCP’ye ekle

Console → **Compute Engine** → **Metadata** → **SSH Keys** → **Edit**

Şu **tek satırı** yapıştır (başına kullanıcı adı şart):

```
rushpaybusiness:ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOO8Hd52sXSMmukFUY94QkD3Z9X0wrIw9lnNcX3kQe/E rushpaybusiness@gmail.com
```

**Save** → 1–2 dakika bekle.

---

## Adım 2 — Mac’ten doğru komut

```bash
ssh -i ~/.ssh/id_ed25519 rushpaybusiness@34.104.243.96
```

Kalıcı SSH config (Mac):

```bash
mkdir -p ~/.ssh
cat >> ~/.ssh/config <<'EOF'

Host elite-gcp
  HostName 34.104.243.96
  User rushpaybusiness
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

Sonra: `ssh elite-gcp`

---

## Hâlâ olmuyorsa — Tarayıcı SSH (en garanti)

1. GCP Console → VM → **SSH** (tarayıcı terminali)
2. Sunucuda çalıştır:

```bash
whoami
```

Çıkan isim senin gerçek kullanıcı adın (ör. `pro` veya `rushpaybusiness`).

Mac key’i elle ekle:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOO8Hd52sXSMmukFUY94QkD3Z9X0wrIw9lnNcX3kQe/E rushpaybusiness@gmail.com' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Mac’ten (whoami çıktısıyla):

```bash
ssh -i ~/.ssh/id_ed25519 KULLANICI@34.104.243.96
```

---

## Kod yükleme (SSH çalışınca)

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner
bash deploy/gcp_upload_from_mac.sh rushpaybusiness@34.104.243.96
```

---

## Önemli: bootstrap nerede çalışır?

`gcp_demo_bootstrap.sh` **sadece Ubuntu sunucuda** çalışır (`apt-get` gerekir).

Mac’te çalıştırırsan `apt-get: command not found` hatası alırsın — bootstrap’ı **GCP SSH penceresinde** çalıştır:

```bash
cd /opt/binancex/predmarket-scanner
sudo bash deploy/gcp_demo_bootstrap.sh
```

(Kod önce `gcp_upload_from_mac.sh` ile yüklenmiş olmalı.)
