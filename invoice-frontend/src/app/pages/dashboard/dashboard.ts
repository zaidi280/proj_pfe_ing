import { Component, OnInit, ChangeDetectorRef, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { API_URL } from '../../app.config';
import { Chart, registerables } from 'chart.js';
import { registerLocaleData } from '@angular/common';
import localeFr from '@angular/common/locales/fr';
import { LOCALE_ID } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { AuthService } from '../../services/auth';

registerLocaleData(localeFr);

Chart.register(...registerables);

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink, MatIconModule],
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.css']
})
export class DashboardComponent implements OnInit {
  @ViewChild('chartStatut')  chartStatutRef!:  ElementRef;
  @ViewChild('chartVendeur') chartVendeurRef!: ElementRef;
  @ViewChild('chartMensuel') chartMensuelRef!: ElementRef;

  private chartStatut?: Chart;
  private chartVendeur?: Chart;
  private chartMensuel?: Chart;

  stats: any = {
    total_factures: 0, total_ttc: 0, vendeurs: 0, clients: 0,
    max_ttc: 0, min_ttc: 0, payment_rate: 0, reglees: 0, non_reglees: 0,
  };

  invoices: any[] = [];
  monthlyRange: '6m' | '12m' | 'all' = '12m';
  loading  = true;
  today    = new Date();
  userDisplayName = 'Admin';

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef,
    private auth: AuthService
  ) {}

  private formatFixed3(value: number): string {
    const sign = value < 0 ? '-' : '';
    const [intPart, fracPart] = Math.abs(value).toFixed(3).split('.');
    const groupedInt = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return `${sign}${groupedInt}.${fracPart}`;
  }

  private monthKeyFromDate(value: any): string | null {
    if (!value) return null;
    const raw = String(value).trim();
    if (!raw) return null;

    const fr = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:\s+.*)?$/);
    if (fr) {
      const [, dd, mm, yyyy] = fr;
      if (Number(mm) >= 1 && Number(mm) <= 12) {
        return `${yyyy}-${mm}`;
      }
    }

    const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (iso) {
      const [, yyyy, mm] = iso;
      if (Number(mm) >= 1 && Number(mm) <= 12) {
        return `${yyyy}-${mm}`;
      }
    }

    // Generic Date fallback (handles locale/date-time variants)
    const parsed = new Date(raw);
    if (!Number.isNaN(parsed.getTime())) {
      const yyyy = String(parsed.getFullYear());
      const mm = String(parsed.getMonth() + 1).padStart(2, '0');
      return `${yyyy}-${mm}`;
    }

    return null;
  }

  normalizePaymentStatus(value: any): 'Payé' | 'En attente' | 'En retard' | 'N/A' {
    const s = String(value || '').trim().toLowerCase();
    if (!s) return 'N/A';

    if (s.includes('regl') || s.includes('régl') || s.includes('pay')) {
      return 'Payé';
    }
    if (s.includes('attente')) {
      return 'En attente';
    }
    if (s.includes('retard')) {
      return 'En retard';
    }
    return 'N/A';
  }

  private monthLabel(key: string): string {
    const m = key.match(/^(\d{4})-(\d{2})$/);
    if (!m) return key;
    return `${m[2]}/${m[1]}`;
  }

  private compactDt(value: number): string {
    return new Intl.NumberFormat('fr-FR', {
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(value);
  }

  private truncateLabel(text: string, maxLen: number): string {
    if (text.length <= maxLen) return text;
    return `${text.slice(0, Math.max(0, maxLen - 1)).trim()}…`;
  }

  private tickStep(length: number, target: number): number {
    if (length <= target) return 1;
    return Math.ceil(length / target);
  }

  setMonthlyRange(range: '6m' | '12m' | 'all'): void {
    if (this.monthlyRange === range) return;
    this.monthlyRange = range;
    if (!this.loading) {
      this.buildChartMensuel();
      this.cdr.detectChanges();
    }
  }

  private filterMonthKeys(sortedKeys: string[]): string[] {
    if (this.monthlyRange === 'all') return sortedKeys;

    const limit = this.monthlyRange === '6m' ? 6 : 12;
    if (sortedKeys.length <= limit) return sortedKeys;
    return sortedKeys.slice(-limit);
  }

  private resolveMonthKey(invoice: any): string | null {
    const candidates = [invoice?.date_facture, invoice?.saved_at, invoice?.created_at];
    for (const value of candidates) {
      const key = this.monthKeyFromDate(value);
      if (key) return key;
    }
    return null;
  }

  ngOnInit() {
    const user = this.auth.getCurrentUser();
    this.userDisplayName = user?.display_name?.trim() || user?.username?.trim() || 'Admin';

    this.http.get<any[]>(`${API_URL}/invoices`).subscribe({
      next: (data) => {
        this.invoices = data;
        const ttcs = data.map(i => this.toDT(i.total_ttc, i.devise)).filter(v => v > 0);

        this.stats = {
          total_factures: data.length,
          total_ttc:      data.reduce((s, i) => s + this.toDT(i.total_ttc, i.devise), 0),
          vendeurs:       new Set(data.map(i => i.vendeur_nom).filter(Boolean)).size,
          clients:        new Set(data.map(i => i.client_nom).filter(Boolean)).size,
          max_ttc:        ttcs.length ? Math.max(...ttcs) : 0,
          min_ttc:        ttcs.length ? Math.min(...ttcs) : 0,
          reglees:        data.filter(i => this.normalizePaymentStatus(i.statut_paiement) === 'Payé').length,
          non_reglees:    data.filter(i => this.normalizePaymentStatus(i.statut_paiement) !== 'Payé').length,
        };
        this.stats.payment_rate = this.stats.total_factures
          ? (this.stats.reglees / this.stats.total_factures) * 100
          : 0;

        this.loading = false;
        this.cdr.detectChanges();
        setTimeout(() => this.buildCharts(), 500);
      },
      error: () => { this.loading = false; this.cdr.detectChanges(); }
    });
  }

  private parseAmount(value: any): number | null {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : null;
    }

    if (typeof value !== 'string') {
      return null;
    }

    let s = value.trim();
    if (!s) {
      return null;
    }

    s = s
      .replace(/\u00A0/g, '')
      .replace(/\s+/g, '')
      .replace(/[^\d,.-]/g, '')
      .replace(/(?!^)-/g, '');

    if (!s || s === '-' || s === ',' || s === '.') {
      return null;
    }

    const lastComma = s.lastIndexOf(',');
    const lastDot = s.lastIndexOf('.');
    const decimalIndex = Math.max(lastComma, lastDot);

    let normalized = '';
    if (decimalIndex >= 0) {
      const intPart = s.slice(0, decimalIndex).replace(/[.,]/g, '');
      const fracPart = s.slice(decimalIndex + 1).replace(/[^\d]/g, '');
      normalized = fracPart ? `${intPart}.${fracPart}` : intPart;
    } else {
      normalized = s.replace(/[.,]/g, '');
    }

    if (s.startsWith('-') && normalized) {
      normalized = `-${normalized}`;
    }

    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  }

  toDT(amount: any, devise: string): number {
    const numericAmount = this.parseAmount(amount);
    if (numericAmount === null) return 0;
    if (devise === 'EUR') return numericAmount * 3.40;
    if (devise === 'USD') return numericAmount * 2.92;
    return numericAmount;
  }

  formatRawAmount(value: any): string {
    const parsed = this.parseAmount(value);
    if (parsed === null) {
      const raw = typeof value === 'string' ? value.trim() : '';
      return raw || '—';
    }
    return this.formatFixed3(parsed);
  }

  displayAmount(amount: any, devise: string): string {
    const parsed = this.parseAmount(amount);
    if (parsed === null) {
      const raw = typeof amount === 'string' ? amount.trim() : '';
      if (!raw) return '—';
      return devise ? `${raw} ${devise}` : raw;
    }
    if (devise === 'EUR' || devise === 'USD') {
      return `${this.formatFixed3(parsed)} ${devise} (${this.formatFixed3(this.toDT(parsed, devise))} DT)`;
    }
    return `${this.formatFixed3(parsed)} DT`;
  }

  buildCharts() {
    this.buildChartStatut();
    this.buildChartVendeur();
    this.buildChartMensuel();
    this.cdr.detectChanges();
  }

  buildChartStatut() {
    if (!this.chartStatutRef) return;
    this.chartStatut?.destroy();
    const counts: any = { 'Payé': 0, 'En attente': 0, 'En retard': 0, 'N/A': 0 };
    this.invoices.forEach(i => {
      const s = this.normalizePaymentStatus(i.statut_paiement);
      counts[s] = (counts[s] || 0) + 1;
    });
    this.chartStatut = new Chart(this.chartStatutRef.nativeElement, {
      type: 'doughnut',
      data: {
        labels: Object.keys(counts),
        datasets: [{
          data: Object.values(counts),
          backgroundColor: ['#22c55e', '#f59e0b', '#ef4444', '#e2e8f0'],
          borderWidth: 0,
          hoverOffset: 8,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '70%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              padding: 14,
              usePointStyle: true,
              pointStyle: 'circle',
              font: { size: 11 },
            },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${ctx.formattedValue}`,
            },
          },
        }
      }
    });
  }

  buildChartVendeur() {
    if (!this.chartVendeurRef) return;
    this.chartVendeur?.destroy();
    const vendeurTtc: any = {};
    this.invoices.forEach(i => {
      const v = i.vendeur_nom || 'Inconnu';
      vendeurTtc[v] = (vendeurTtc[v] || 0) + this.toDT(i.total_ttc, i.devise);
    });

    const sortedEntries = Object.entries(vendeurTtc)
      .sort((a, b) => (b[1] as number) - (a[1] as number));

    const TOP_LIMIT = 12;
    const topEntries = sortedEntries.slice(0, TOP_LIMIT);
    const othersTotal = sortedEntries
      .slice(TOP_LIMIT)
      .reduce((sum, [, amount]) => sum + (amount as number), 0);

    const labels = topEntries.map(([name]) => name);
    const values = topEntries.map(([, amount]) => amount as number);

    if (othersTotal > 0) {
      labels.push('Autres vendeurs');
      values.push(othersTotal);
    }

    this.chartVendeur = new Chart(this.chartVendeurRef.nativeElement, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Total TTC (DT)',
          data: values,
          backgroundColor: labels.map((_, idx) => {
            const palette = ['#6366f1', '#8b5cf6', '#14b8a6', '#f59e0b', '#ec4899'];
            return palette[idx % palette.length];
          }),
          borderRadius: 8,
          borderSkipped: false as any,
          maxBarThickness: 22,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${this.formatFixed3(Number(ctx.raw || 0))} DT`,
              title: (items) => items[0]?.label || '',
            },
          },
        },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            ticks: {
              callback: (value) => this.compactDt(Number(value)),
              maxTicksLimit: 6,
            },
          },
          y: {
            grid: { display: false },
            ticks: {
              callback: (value) => {
                const index = Number(value);
                const raw = labels[index] || '';
                return this.truncateLabel(raw, 22);
              },
            },
          }
        }
      }
    });
  }

  buildChartMensuel() {
    if (!this.chartMensuelRef) return;
    this.chartMensuel?.destroy();
    const mensuel: any = {};
    this.invoices.forEach(i => {
      const monthKey = this.resolveMonthKey(i);
      if (monthKey) {
        mensuel[monthKey] = (mensuel[monthKey] || 0) + this.toDT(i.total_ttc, i.devise);
      }
    });
    const sorted = this.filterMonthKeys(Object.keys(mensuel).sort());
    const labels = sorted.map(k => this.monthLabel(k));
    const values = sorted.map(k => mensuel[k]);
    const tickEvery = this.tickStep(labels.length, 12);

    this.chartMensuel = new Chart(this.chartMensuelRef.nativeElement, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Total TTC (DT)',
          data: values,
          borderColor: '#6366f1',
          backgroundColor: 'rgba(99,102,241,0.08)',
          borderWidth: 3,
          fill: true,
          tension: 0.3,
          pointBackgroundColor: '#6366f1',
          pointRadius: labels.length > 24 ? 2 : 4,
          pointHoverRadius: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${this.formatFixed3(Number(ctx.raw || 0))} DT`,
            },
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            ticks: {
              callback: (value) => this.compactDt(Number(value)),
              maxTicksLimit: 6,
            },
          },
          x: {
            grid: { display: false },
            ticks: {
              autoSkip: false,
              maxRotation: 50,
              minRotation: 50,
              callback: (_value, index) => (index % tickEvery === 0 ? labels[index] : ''),
            },
          }
        }
      }
    });
  }
}