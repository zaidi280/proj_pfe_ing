import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_URL } from '../../app.config';
import { Router, RouterLink } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import Swal from 'sweetalert2';
import { InvoiceService } from '../../services/invoice';
import { AuthService } from '../../services/auth';

@Component({
  selector: 'app-invoices',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, MatIconModule],
  templateUrl: './invoices.html',
  styleUrls: ['./invoices.css']
})
export class InvoicesComponent implements OnInit {
  invoices:  any[] = [];
  filtered:  any[] = [];
  loading          = true;
  search           = '';
  filterVendeur    = '';
  filterStatut     = '';
  vendeurs: string[] = [];
  canDeleteInvoices = false;

  // Pagination
  currentPage = 1;
  pageSize    = 10;

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef,
    public router: Router,
    private invoiceService: InvoiceService,
    private authService: AuthService,
  ) {}

  ngOnInit() {
    this.canDeleteInvoices = this.authService.hasRole('admin');
    this.http.get<any[]>(`${API_URL}/invoices`).subscribe({
      next: (data) => {
        this.invoices  = data;
        this.filtered  = data;
        this.vendeurs  = [...new Set(data.map((i: any) => i.vendeur_nom).filter(Boolean))];
        this.loading   = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        console.log('Erreur:', err);
        this.loading = false;
        this.cdr.detectChanges();
      }
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

  convertToDT(amount: any, devise: string): number {
    const numericAmount = this.parseAmount(amount);
    if (numericAmount === null) return 0;
    if (devise === 'EUR') return numericAmount * 3.40;
    if (devise === 'USD') return numericAmount * 2.92;
    return numericAmount;
  }

  formatRawAmount(amount: any): string {
    const parsed = this.parseAmount(amount);
    if (parsed === null) {
      const raw = typeof amount === 'string' ? amount.trim() : '';
      return raw || '—';
    }
    return parsed.toFixed(3);
  }

  displayAmount(amount: any, devise: string): string {
    const parsed = this.parseAmount(amount);
    if (parsed === null) {
      const raw = typeof amount === 'string' ? amount.trim() : '';
      if (!raw) return '—';
      return devise ? `${raw} ${devise}` : raw;
    }

    if (devise === 'EUR' || devise === 'USD') {
      const converted = this.convertToDT(parsed, devise);
      return `${parsed.toFixed(3)} ${devise} (${converted.toFixed(3)} DT)`;
    }
    return `${parsed.toFixed(3)} DT`;
  }

  applyFilters() {
    this.currentPage = 1;
    this.filtered = this.invoices.filter(inv => {
      const matchSearch  = !this.search ||
        inv.numero_facture?.toLowerCase().includes(this.search.toLowerCase()) ||
        inv.vendeur_nom?.toLowerCase().includes(this.search.toLowerCase()) ||
        inv.client_nom?.toLowerCase().includes(this.search.toLowerCase());
      const matchVendeur = !this.filterVendeur || inv.vendeur_nom === this.filterVendeur;
      const matchStatut  = !this.filterStatut  || inv.statut_paiement === this.filterStatut;
      return matchSearch && matchVendeur && matchStatut;
    });
  }

  resetFilters() {
    this.search        = '';
    this.filterVendeur = '';
    this.filterStatut  = '';
    this.filtered      = this.invoices;
    this.currentPage   = 1;
  }

  totalTTC(): number {
    return this.filtered.reduce((s: number, i: any) => {
      return s + this.convertToDT(i.total_ttc, i.devise || 'DT');
    }, 0);
  }

  // ── Pagination ─────────────────────────────────────────────
  totalPages(): number {
    return Math.ceil(this.filtered.length / this.pageSize) || 1;
  }

  pageStart(): number {
    return (this.currentPage - 1) * this.pageSize;
  }

  pageEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.filtered.length);
  }

  pagedInvoices(): any[] {
    return this.filtered.slice(this.pageStart(), this.pageEnd());
  }

  pages(): number[] {
    const total = this.totalPages();
    const current = this.currentPage;
    const pages: number[] = [];
    let start = Math.max(1, current - 2);
    let end   = Math.min(total, current + 2);
    if (end - start < 4) {
      if (start === 1) end = Math.min(total, start + 4);
      else start = Math.max(1, end - 4);
    }
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }

  goToPage(p: number) {
    this.currentPage = p;
    this.cdr.detectChanges();
  }

  prevPage() {
    if (this.currentPage > 1) { this.currentPage--; this.cdr.detectChanges(); }
  }

  nextPage() {
    if (this.currentPage < this.totalPages()) { this.currentPage++; this.cdr.detectChanges(); }
  }

  onPageSizeChange() {
    this.currentPage = 1;
    this.cdr.detectChanges();
  }
  deleteInvoice(inv: any) {
  if (!this.canDeleteInvoices) {
    return;
  }

  Swal.fire({
    title: 'Supprimer la facture ?',
    text: `Facture ${inv.numero_facture} — Cette action est irréversible.`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    cancelButtonColor: '#6b7280',
    confirmButtonText: '🗑️ Oui, supprimer',
    cancelButtonText: 'Annuler',
  }).then((result) => {
    if (result.isConfirmed) {
      this.invoiceService.deleteInvoice(inv.id).subscribe({
        next: () => {
          this.invoices = this.invoices.filter(i => i.id !== inv.id);
          this.applyFilters();
          this.cdr.detectChanges();
          Swal.fire({
            title: 'Supprimée !',
            text: `La facture ${inv.numero_facture} a été supprimée.`,
            icon: 'success',
            confirmButtonColor: '#6366f1',
            timer: 2000,
            timerProgressBar: true,
          });
        },
        error: () => {
          Swal.fire({
            title: 'Erreur',
            text: 'Erreur lors de la suppression.',
            icon: 'error',
            confirmButtonColor: '#6366f1',
          });
        }
      });
    }
  });
}
}