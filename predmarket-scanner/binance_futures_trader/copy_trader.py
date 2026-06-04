"""
Binance Futures Copy Trading Module
====================================
En iyi performans gösteren yatırımcıları takip edip pozisyonlarını aynalar.

Özellikler:
- Leaderboard'dan top traders bulma
- Trader pozisyonlarını real-time izleme
- Pozisyonları risk yönetimiyle aynalama
- Performance tracking ve raporlama

Eğitim/strateji modülünden BAĞIMSIZ çalışır.
"""
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import httpx
from rich.console import Console

console = Console()


@dataclass
class TraderProfile:
    """Takip edilen trader profili"""
    uid: str  # Encrypted UID
    nickname: str
    rank: int
    pnl: float
    roi: float
    win_rate: float
    follower_count: int
    last_update: int  # timestamp
    is_active: bool = True
    min_position_usd: float = 50.0  # Bu trader için min pozisyon
    max_position_usd: float = 500.0  # Bu trader için max pozisyon
    copy_multiplier: float = 1.0  # Pozisyon boyutunu çarpan
    auto_discovered: bool = False  # Otomatik keşif ile mi eklendi


@dataclass
class TraderPosition:
    """Trader'ın açık pozisyonu"""
    trader_uid: str
    symbol: str
    side: str  # LONG/SHORT
    leverage: int
    entry_price: float
    mark_price: float
    pnl: float
    size: float  # Position size in contracts
    update_time: int


@dataclass
class MirroredPosition:
    """Bizim aynalanan pozisyonumuz"""
    trader_uid: str
    trader_nickname: str
    symbol: str
    side: str
    our_entry_price: float
    our_size_usd: float
    our_leverage: int
    opened_at: int
    trader_entry_price: Optional[float] = None
    is_closed: bool = False
    closed_at: Optional[int] = None
    pnl: Optional[float] = None


class BinanceLeaderboardAPI:
    """
    Binance Futures Leaderboard API wrapper
    Binance'ın public API'sini kullanır (API key gerektirmez)
    """
    
    BASE_URL = "https://www.binance.com/bapi/futures"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key  # Şu an için kullanılmıyor, public API
        self.client = httpx.Client(timeout=30.0)
    
    def _headers(self) -> Dict[str, str]:
        """Binance'ın beklediği standart headers"""
        return {
            "authority": "www.binance.com",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.8",
            "cache-control": "no-cache",
            "clienttype": "web",
            "content-type": "application/json",
            "lang": "en",
            "origin": "https://www.binance.com",
            "pragma": "no-cache",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
    
    def get_leaderboard(
        self,
        trade_type: str = "PERPETUAL",  # PERPETUAL, DELIVERY
        stat_type: str = "PNL",  # PNL, ROI
        period: str = "MONTHLY",  # DAILY, WEEKLY, MONTHLY, ALL
        limit: int = 50
    ) -> List[Dict]:
        """
        Leaderboard'dan top traders getir
        
        Returns:
            List of trader dicts with: encryptedUid, nickname, rank, value (PnL ya da ROI)
        """
        try:
            url = f"{self.BASE_URL}/v3/public/future/leaderboard/getLeaderboardRank"
            
            # Binance API payload
            payload = {
                "tradeType": trade_type,
                "statisticsType": stat_type,
                "periodType": period,
                "isShared": True,  # Sadece position paylaşan traderlar
                "isTrader": True   # Sadece gerçek traderlar
            }
            
            resp = self.client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()
            
            # Binance response format: {"success": true, "data": [...]}
            if not result.get("success", False):
                console.print(f"[yellow]⚠ API returned success=false: {result.get('message')}[/yellow]")
                return []
            
            data = result.get("data", [])
            
            # Her trader için detay bilgisi lazım - UID'leri toplayalım
            traders = []
            for item in data[:limit]:
                trader_info = {
                    "encryptedUid": item.get("encryptedUid", ""),
                    "nickname": item.get("nickname", "Unknown"),
                    "rank": item.get("rank", 999),
                    "value": item.get("value", 0.0),  # PnL or ROI
                }
                
                # Ek detaylar varsa
                if "pnl" in item:
                    trader_info["pnl"] = item["pnl"]
                if "roi" in item:
                    trader_info["roi"] = item["roi"]
                else:
                    # Value ROI ise yüzde olarak kaydet
                    if stat_type == "ROI":
                        trader_info["roi"] = trader_info["value"]
                    else:
                        trader_info["pnl"] = trader_info["value"]
                
                # Win rate ve follower bilgisi için ayrı çağrı gerekebilir
                # Şimdilik placeholder
                trader_info.setdefault("winRate", 0.0)
                trader_info.setdefault("followerCount", 0)
                
                traders.append(trader_info)
            
            return traders
            
        except Exception as e:
            console.print(f"[red]❌ Leaderboard fetch error: {e}[/red]")
            return []
    
    def get_trader_positions(
        self,
        encrypted_uid: str,
        trade_type: str = "PERPETUAL"
    ) -> List[Dict]:
        """
        Belirli bir trader'ın açık pozisyonlarını getir
        
        Returns:
            List of position dicts with: symbol, side, leverage, entryPrice, markPrice, pnl, amount, updateTime
        """
        try:
            url = f"{self.BASE_URL}/v1/public/future/leaderboard/getOtherPosition"
            
            payload = {
                "encryptedUid": encrypted_uid,
                "tradeType": trade_type
            }
            
            resp = self.client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()
            
            # Binance response: {"success": true, "data": {"otherPositionRetList": [...]}}
            if not result.get("success", False):
                return []
            
            data = result.get("data", {})
            positions = data.get("otherPositionRetList", [])
            
            # Format'ı normalize et
            normalized = []
            for pos in positions:
                # LONG mu SHORT mu? Binance amount ile belirtir (+/-)
                amount = pos.get("amount", 0.0)
                side = "LONG" if amount > 0 else "SHORT"
                
                normalized.append({
                    "symbol": pos.get("symbol", ""),
                    "side": side,
                    "leverage": pos.get("leverage", 1),
                    "entryPrice": pos.get("entryPrice", 0.0),
                    "markPrice": pos.get("markPrice", 0.0),
                    "pnl": pos.get("pnl", 0.0),
                    "amount": abs(amount),
                    "updateTime": pos.get("updateTimeStamp", 0)
                })
            
            return normalized
            
        except Exception as e:
            console.print(f"[yellow]⚠ Trader {encrypted_uid[:8]}... positions fetch error: {e}[/yellow]")
            return []
    
    def get_trader_info(self, encrypted_uid: str) -> Optional[Dict]:
        """
        Trader'ın detay bilgilerini getir (follower count, win rate vs)
        """
        try:
            url = f"{self.BASE_URL}/v2/public/future/leaderboard/getOtherLeaderboardBaseInfo"
            
            payload = {"encryptedUid": encrypted_uid}
            
            resp = self.client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()
            
            if not result.get("success", False):
                return None
            
            data = result.get("data", {})
            return {
                "nickname": data.get("nickName", "Unknown"),
                "followerCount": data.get("followerCount", 0),
                "positionShared": data.get("positionShared", False),
                "twitterUrl": data.get("twitterUrl", ""),
                "introduction": data.get("introduction", "")
            }
            
        except Exception as e:
            console.print(f"[dim yellow]⚠ Trader {encrypted_uid[:8]}... info fetch error: {e}[/dim yellow]")
            return None


class CopyTradingEngine:
    """
    Copy Trading ana motoru
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        data_dir: str = "data/copy_trading",
        max_traders: int = 10,
        min_trader_roi: float = 50.0,  # %50 minimum ROI
        min_trader_wr: float = 0.55,  # %55 minimum win rate
        max_mirror_positions: int = 5,
        total_capital_usd: float = 5000.0,
        copy_allocation_pct: float = 30.0,  # Total sermayenin %30'u copy trading için
    ):
        self.api = BinanceLeaderboardAPI(api_key)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_traders = max_traders
        self.min_trader_roi = min_trader_roi
        self.min_trader_wr = min_trader_wr
        self.max_mirror_positions = max_mirror_positions
        self.total_capital_usd = total_capital_usd
        self.copy_allocation_pct = copy_allocation_pct
        
        self.tracked_traders: Dict[str, TraderProfile] = {}
        self.mirrored_positions: List[MirroredPosition] = []
        
        self._load_state()
    
    def _load_state(self):
        """Kayıtlı trader ve pozisyonları yükle"""
        traders_file = self.data_dir / "tracked_traders.json"
        positions_file = self.data_dir / "mirrored_positions.json"
        
        if traders_file.exists():
            try:
                with open(traders_file) as f:
                    data = json.load(f)
                    _fields = {f.name for f in TraderProfile.__dataclass_fields__.values()}
                    self.tracked_traders = {
                        uid: TraderProfile(
                            **{k: v for k, v in profile.items() if k in _fields}
                        )
                        for uid, profile in data.items()
                    }
                console.print(f"[green]✓ Loaded {len(self.tracked_traders)} tracked traders[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠ Failed to load traders: {e}[/yellow]")
        
        if positions_file.exists():
            try:
                with open(positions_file) as f:
                    data = json.load(f)
                    self.mirrored_positions = [MirroredPosition(**pos) for pos in data]
                console.print(f"[green]✓ Loaded {len(self.mirrored_positions)} mirrored positions[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠ Failed to load positions: {e}[/yellow]")
    
    def _save_state(self):
        """Trader ve pozisyonları kaydet"""
        traders_file = self.data_dir / "tracked_traders.json"
        positions_file = self.data_dir / "mirrored_positions.json"
        
        with open(traders_file, "w") as f:
            data = {uid: asdict(profile) for uid, profile in self.tracked_traders.items()}
            json.dump(data, f, indent=2)
        
        with open(positions_file, "w") as f:
            data = [asdict(pos) for pos in self.mirrored_positions]
            json.dump(data, f, indent=2)
    
    def discover_top_traders(self, period: str = "MONTHLY") -> List[TraderProfile]:
        """
        Leaderboard'dan en iyi traderları bul ve filtrele
        """
        console.print(f"\n[cyan]🔍 Discovering top traders ({period})...[/cyan]")
        
        raw_traders = self.api.get_leaderboard(
            trade_type="PERPETUAL",
            stat_type="ROI",  # ROI'ye göre sırala
            period=period,
            limit=100
        )
        
        if not raw_traders:
            console.print("[yellow]⚠ No traders returned from leaderboard[/yellow]")
            return []
        
        console.print(f"[blue]Fetched {len(raw_traders)} traders from leaderboard[/blue]")
        
        candidates = []
        for idx, t in enumerate(raw_traders):
            roi = t.get("roi", 0)
            
            # Win rate bilgisi leaderboard'da yok, trader info'dan almak gerekir
            # Ancak her trader için ayrı istek maliyetli, şimdilik placeholder
            # Sadece ROI kriterine göre filtrele
            if roi >= self.min_trader_roi:
                # İlk 20 için detay bilgi çek (rate limit için)
                extra_info = {}
                if idx < 20:
                    trader_detail = self.api.get_trader_info(t["encryptedUid"])
                    if trader_detail:
                        extra_info["follower_count"] = trader_detail.get("followerCount", 0)
                        time.sleep(0.1)  # Rate limit için bekle
                
                profile = TraderProfile(
                    uid=t["encryptedUid"],
                    nickname=t.get("nickname", "Unknown"),
                    rank=t.get("rank", 999),
                    pnl=t.get("pnl", 0.0),
                    roi=roi,
                    win_rate=0.0,  # Leaderboard'da yok, TODO: Ayrı endpoint'ten al
                    follower_count=extra_info.get("follower_count", 0),
                    last_update=int(time.time() * 1000)
                )
                candidates.append(profile)
        
        # En iyi N trader'ı seç (rank + ROI kombinasyonu, WR yok şimdilik)
        candidates.sort(key=lambda x: (x.rank, -x.roi))
        top_traders = candidates[:self.max_traders]
        
        console.print(f"[green]✓ Found {len(top_traders)} qualified traders (ROI ≥ {self.min_trader_roi}%)[/green]")
        for tr in top_traders[:5]:  # İlk 5'ini göster
            console.print(
                f"  #{tr.rank} {tr.nickname} - ROI: {tr.roi:.1f}%, "
                f"Followers: {tr.follower_count}"
            )
        
        return top_traders
    
    def update_tracked_traders(self, new_traders: List[TraderProfile]):
        """Takip edilen trader listesini güncelle"""
        for trader in new_traders:
            if trader.uid not in self.tracked_traders:
                self.tracked_traders[trader.uid] = trader
                console.print(f"[green]➕ Added trader: {trader.nickname} (ROI: {trader.roi}%)[/green]")
            else:
                # Mevcut trader'ı güncelle
                existing = self.tracked_traders[trader.uid]
                existing.rank = trader.rank
                existing.pnl = trader.pnl
                existing.roi = trader.roi
                existing.win_rate = trader.win_rate
                existing.follower_count = trader.follower_count
                existing.last_update = trader.last_update
        
        self._save_state()
    
    def scan_trader_positions(self) -> List[TraderPosition]:
        """
        Tüm takip edilen traderların pozisyonlarını tara
        """
        all_positions = []
        
        for uid, trader in self.tracked_traders.items():
            if not trader.is_active:
                continue
            
            positions = self.api.get_trader_positions(uid, trade_type="PERPETUAL")
            
            for pos in positions:
                tp = TraderPosition(
                    trader_uid=uid,
                    symbol=pos.get("symbol", ""),
                    side=pos.get("side", "LONG"),
                    leverage=pos.get("leverage", 1),
                    entry_price=pos.get("entryPrice", 0.0),
                    mark_price=pos.get("markPrice", 0.0),
                    pnl=pos.get("pnl", 0.0),
                    size=pos.get("amount", 0.0),
                    update_time=pos.get("updateTime", 0)
                )
                all_positions.append(tp)
        
        return all_positions
    
    def should_mirror_position(self, trader_pos: TraderPosition) -> bool:
        """
        Bu pozisyonu aynalayacak mıyız?
        
        Kriterler:
        - Aktif mirror sayısı limit altında mı
        - Bu symbol için zaten mirror var mı
        - Trader'ın profili uygun mu
        """
        # Max mirror sayısını aşmış mı?
        active_mirrors = [p for p in self.mirrored_positions if not p.is_closed]
        if len(active_mirrors) >= self.max_mirror_positions:
            return False
        
        # Bu symbol için zaten mirror var mı?
        for mirror in active_mirrors:
            if mirror.symbol == trader_pos.symbol and mirror.side == trader_pos.side:
                return False  # Duplicate pozisyon açma
        
        # Trader profili
        trader = self.tracked_traders.get(trader_pos.trader_uid)
        if not trader or not trader.is_active:
            return False
        
        return True
    
    def calculate_mirror_size(self, trader_pos: TraderPosition) -> float:
        """
        Aynalayacağımız pozisyon büyüklüğünü hesapla (USD)
        
        Copy allocation capital içinde, trader'ın ROI'sine göre ağırlıklandır
        """
        trader = self.tracked_traders.get(trader_pos.trader_uid)
        if not trader:
            return 0.0
        
        # Copy trading için ayrılan total capital
        copy_capital = self.total_capital_usd * (self.copy_allocation_pct / 100.0)
        
        # Her trader için base allocation
        base_allocation = copy_capital / max(len(self.tracked_traders), 1)
        
        # Trader'ın ROI'sine göre çarpan (ROI càlıksa daha fazla sermaye)
        roi_multiplier = min(trader.roi / 100.0, 2.0)  # Max 2x
        
        # Trader'ın copy_multiplier'ı (manuel ayar)
        position_usd = base_allocation * roi_multiplier * trader.copy_multiplier
        
        # Min/max clamp
        position_usd = max(trader.min_position_usd, min(position_usd, trader.max_position_usd))
        
        return position_usd
    
    def mirror_position(self, trader_pos: TraderPosition, dry_run: bool = True) -> Optional[MirroredPosition]:
        """
        Trader pozisyonunu aynala (ya da dry-run)
        
        Args:
            trader_pos: Trader'ın pozisyonu
            dry_run: True ise gerçek trade açmaz, sadece simüle eder
        
        Returns:
            MirroredPosition ya da None
        """
        if not self.should_mirror_position(trader_pos):
            return None
        
        trader = self.tracked_traders.get(trader_pos.trader_uid)
        if not trader:
            return None
        
        size_usd = self.calculate_mirror_size(trader_pos)
        
        mirror = MirroredPosition(
            trader_uid=trader_pos.trader_uid,
            trader_nickname=trader.nickname,
            symbol=trader_pos.symbol,
            side=trader_pos.side,
            our_entry_price=trader_pos.mark_price,  # Mark price ile gireriz
            our_size_usd=size_usd,
            our_leverage=min(trader_pos.leverage, 10),  # Max 10x için güvenlik
            opened_at=int(time.time() * 1000),
            trader_entry_price=trader_pos.entry_price
        )
        
        if dry_run:
            console.print(
                f"[yellow]🔷 DRY RUN: Would mirror {trader.nickname}'s {trader_pos.side} "
                f"{trader_pos.symbol} @ {trader_pos.mark_price:.4f} "
                f"(${size_usd:.2f}, {mirror.our_leverage}x)[/yellow]"
            )
        else:
            # Gerçek trade açma kodu buraya gelecek
            # TODO: Binance API client ile order placement
            console.print(
                f"[green]✅ MIRRORED: {trader.nickname}'s {trader_pos.side} "
                f"{trader_pos.symbol} @ {trader_pos.mark_price:.4f} "
                f"(${size_usd:.2f}, {mirror.our_leverage}x)[/green]"
            )
            self.mirrored_positions.append(mirror)
            self._save_state()
        
        return mirror
    
    def sync_mirror_exits(self, current_trader_positions: List[TraderPosition], dry_run: bool = True):
        """
        Trader pozisyon kapattıysa bizim de kapatmamız gerekiyor
        """
        active_mirrors = [p for p in self.mirrored_positions if not p.is_closed]
        
        # Trader'ların şu anki açık pozisyonlarını symbol+side ile set yap
        trader_open_set = {
            (tp.trader_uid, tp.symbol, tp.side)
            for tp in current_trader_positions
        }
        
        for mirror in active_mirrors:
            key = (mirror.trader_uid, mirror.symbol, mirror.side)
            if key not in trader_open_set:
                # Trader kapamış, biz de kapatalım
                if dry_run:
                    console.print(
                        f"[yellow]🔷 DRY RUN: Would close mirrored {mirror.side} "
                        f"{mirror.symbol} (Trader closed)[/yellow]"
                    )
                else:
                    # Gerçek pozisyon kapatma kodu
                    # TODO: Binance API client ile position close
                    mirror.is_closed = True
                    mirror.closed_at = int(time.time() * 1000)
                    console.print(
                        f"[red]🔻 CLOSED: Mirrored {mirror.side} {mirror.symbol} "
                        f"(Trader {mirror.trader_nickname} closed)[/red]"
                    )
                    self._save_state()
    
    def run_monitoring_loop(
        self,
        refresh_interval_sec: int = 60,
        discover_interval_sec: int = 3600,  # Her saat yeni trader ara
        dry_run: bool = True
    ):
        """
        Ana monitoring döngüsü
        
        - Her refresh_interval'da trader pozisyonlarını tara
        - Yeni pozisyonları aynala
        - Kapanan pozisyonları kapat
        - Her discover_interval'da leaderboard'dan yeni trader keşfet
        """
        console.print("[bold cyan]🚀 Copy Trading Engine Started[/bold cyan]")
        console.print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE TRADING'}")
        console.print(f"  Max Traders: {self.max_traders}")
        console.print(f"  Max Mirror Positions: {self.max_mirror_positions}")
        console.print(f"  Copy Capital: ${self.total_capital_usd * self.copy_allocation_pct / 100:.2f}\n")
        
        last_discover_time = 0
        
        try:
            while True:
                now = time.time()
                
                # Periodically discover new traders (only if no traders exist)
                if now - last_discover_time > discover_interval_sec:
                    if len(self.tracked_traders) == 0:
                        console.print("[yellow]⚠️  No traders found, attempting auto-discovery...[/yellow]")
                        top_traders = self.discover_top_traders(period="MONTHLY")
                        self.update_tracked_traders(top_traders)
                    last_discover_time = now
                
                # Scan all tracked traders' positions
                console.print(f"\n[cyan]⏱ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC - Scanning positions...[/cyan]")
                
                trader_positions = self.scan_trader_positions()
                console.print(f"[blue]Found {len(trader_positions)} total positions from {len(self.tracked_traders)} traders[/blue]")
                
                # Mirror new positions
                for tp in trader_positions:
                    self.mirror_position(tp, dry_run=dry_run)
                
                # Sync exits
                self.sync_mirror_exits(trader_positions, dry_run=dry_run)
                
                # Status
                active_count = len([p for p in self.mirrored_positions if not p.is_closed])
                console.print(f"[green]Active mirrored positions: {active_count}/{self.max_mirror_positions}[/green]")
                
                time.sleep(refresh_interval_sec)
                
        except KeyboardInterrupt:
            console.print("\n[yellow]⏹ Copy Trading Engine Stopped[/yellow]")
            self._save_state()


def main():
    """Test / Demo"""
    # Not: Artık API key gerektirmiyor, Binance public API kullanılıyor
    
    engine = CopyTradingEngine(
        api_key=None,  # Public API, key gerektirmez
        max_traders=10,
        min_trader_roi=50.0,
        min_trader_wr=0.0,  # Win rate bilgisi leaderboard'da yok, 0 yapıldı
        max_mirror_positions=5,
        total_capital_usd=5000.0,
        copy_allocation_pct=30.0
    )
    
    # Dry run mode ile çalıştır (gerçek trade açmaz)
    engine.run_monitoring_loop(
        refresh_interval_sec=60,
        discover_interval_sec=3600,
        dry_run=True  # Canlı trade için False yap
    )


if __name__ == "__main__":
    main()
