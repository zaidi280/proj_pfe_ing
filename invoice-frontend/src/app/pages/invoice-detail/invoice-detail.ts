import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { API_URL } from '../../app.config';
import Swal from 'sweetalert2';
import { InvoiceService } from '../../services/invoice';
import { AuthService } from '../../services/auth';
@Component({
  selector: 'app-invoice-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './invoice-detail.html',
})
export class InvoiceDetailComponent implements OnInit, OnDestroy {
  invoice:    any    = null;
  loading:    boolean = true;
  editMode:   boolean = false;
  deleting:   boolean = false;
  saving:     boolean = false;
  error:      string  = '';
  success:    string  = '';
  imageUrl:   string  = '';
  invoiceId:  string  = '';
isZoomed  = false;
zoomX     = 50;
zoomY     = 50;
fullscreen = false;
canDeleteInvoice = false;
  constructor(
    private http:  HttpClient,
    private route: ActivatedRoute,
    private router: Router,
    private cdr:   ChangeDetectorRef,
    private invoiceService: InvoiceService,
    private authService: AuthService,
  ) {}

  ngOnInit() {
    this.canDeleteInvoice = this.authService.hasRole('admin');
    this.invoiceId = (this.route.snapshot.paramMap.get('id') || '').trim();
    if (!this.invoiceId) {
      this.error = 'Identifiant facture invalide.';
      this.loading = false;
      return;
    }
    this.loadInvoice();
  }

  ngOnDestroy() {
    this.revokeImageUrl();
  }

  loadInvoice() {
    this.loading = true;
    this.http.get<any>(`${API_URL}/invoices/${this.invoiceId}`).subscribe({
      next: (data) => {
        this.invoice  = this.formatInvoiceForDisplay(data);
        if (!Array.isArray(this.invoice?.lignes)) {
          this.invoice.lignes = [];
        }
        this.loadInvoiceImage();
        this.loading  = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.error   = 'Facture introuvable.';
        this.loading = false;
        this.cdr.detectChanges();
      }
    });
  }

  private loadInvoiceImage() {
    const imageEndpoint = `${API_URL}/invoices/${this.invoiceId}/image`;
    this.http.get(imageEndpoint, { responseType: 'blob' }).subscribe({
      next: (blob) => {
        this.revokeImageUrl();
        this.imageUrl = URL.createObjectURL(blob);
        this.cdr.detectChanges();
      },
      error: () => {
        this.revokeImageUrl();
        this.imageUrl = '';
        this.cdr.detectChanges();
      },
    });
  }

  private revokeImageUrl() {
    if (this.imageUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.imageUrl);
    }
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

  private formatAmountValue(value: any): string {
    const parsed = this.parseAmount(value);
    if (parsed === null) {
      return typeof value === 'string' ? value.trim() : '';
    }
    return parsed.toFixed(3);
  }

  private formatInvoiceForDisplay(invoice: any): any {
    const formatted = { ...(invoice || {}) };

    formatted.total_ht = this.formatAmountValue(formatted.total_ht);
    formatted.montant_tva = this.formatAmountValue(formatted.montant_tva);
    formatted.timbre_fiscal = this.formatAmountValue(formatted.timbre_fiscal);
    formatted.total_ttc = this.formatAmountValue(formatted.total_ttc);

    formatted.lignes = Array.isArray(formatted.lignes)
      ? formatted.lignes.map((line: any) => ({
          ...line,
          prix_unitaire_ht: this.formatAmountValue(line?.prix_unitaire_ht),
          remise_pct: this.formatAmountValue(line?.remise_pct ?? line?.remise),
          montant_ht: this.formatAmountValue(line?.montant_ht),
          taux_tva: line?.taux_tva ?? '',
        }))
      : [];

    return formatted;
  }

  private toDT(amount: any, devise: string): number {
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
    return parsed.toFixed(3);
  }

  formatPercent(value: any): string {
    const parsed = this.parseAmount(value);
    if (parsed === null) {
      const raw = typeof value === 'string' ? value.trim() : '';
      return raw ? `${raw}%` : '—';
    }
    return `${parsed.toFixed(3)}%`;
  }

  displayAmount(amount: any, devise: string): string {
    const parsed = this.parseAmount(amount);
    if (parsed === null) {
      const raw = typeof amount === 'string' ? amount.trim() : '';
      if (!raw) return '—';
      return devise ? `${raw} ${devise}` : raw;
    }
    if (devise === 'EUR' || devise === 'USD') {
      return `${parsed.toFixed(3)} ${devise} (${this.toDT(parsed, devise).toFixed(3)} DT)`;
    }
    return `${parsed.toFixed(3)} DT`;
  }

  toggleEdit() {
    this.editMode = !this.editMode;
    this.success  = '';
    this.error    = '';
    this.cdr.detectChanges();
  }

  addLigne() {
    this.invoice.lignes.push({
      designation: '', code_article: null,
      quantite: 1, unite: null,
      prix_unitaire_ht: null, remise_pct: 0,
      montant_ht: null, taux_tva: null
    });
    this.cdr.detectChanges();
  }

  removeLigne(i: number) {
    this.invoice.lignes.splice(i, 1);
    this.cdr.detectChanges();
  }

  save() {
  this.saving = true;
  this.error  = '';
  this.cdr.detectChanges();

  const payload = {
  source_file:         this.invoice.source_file         || '',
  image_path:          this.invoice.image_path          || '',
  numero_facture:      this.invoice.numero_facture       || '',
  type_document:       this.invoice.type_document        || 'FACTURE',
  date_facture:        this.invoice.date_facture  ? String(this.invoice.date_facture).split('T')[0]  : null,
  date_echeance:       this.invoice.date_echeance ? String(this.invoice.date_echeance).split('T')[0] : null,
  numero_bc:           this.invoice.numero_bc            || null,
  vendeur_nom:         this.invoice.vendeur_nom          || '',
  vendeur_mf:          this.invoice.vendeur_mf           || null,
  vendeur_adresse:     this.invoice.vendeur_adresse      || null,
  vendeur_telephone:   this.invoice.vendeur_telephone    || null,
  vendeur_email:       this.invoice.vendeur_email        || null,
  vendeur_rib:         this.invoice.vendeur_rib          || null,
  client_nom:          this.invoice.client_nom           || null,
  client_mf:           this.invoice.client_mf            || null,
  client_adresse:      this.invoice.client_adresse       || null,
  total_ht:            this.invoice.total_ht             || null,
  taux_tva:            this.invoice.taux_tva             || null,
  montant_tva:         this.invoice.montant_tva          || null,
  timbre_fiscal:       this.invoice.timbre_fiscal        || 0,
  total_ttc:           this.invoice.total_ttc            || null,
  devise:              this.invoice.devise               || 'DT',
  montant_en_lettres:  this.invoice.montant_en_lettres   || null,
  mode_paiement:       this.invoice.mode_paiement        || null,
  statut_paiement:     this.invoice.statut_paiement      || null,
  conditions_paiement: this.invoice.conditions_paiement  || null,
  lignes:              this.invoice.lignes               || [],
};

  this.http.put<any>(`${API_URL}/invoices/${this.invoiceId}`, payload).subscribe({
    next: () => {
      this.saving   = false;
      this.editMode = false;
      this.success  = '✅ Facture mise à jour avec succès !';
      this.cdr.detectChanges();
      setTimeout(() => { this.success = ''; this.cdr.detectChanges(); }, 3000);
    },
    error: (err) => {
      this.saving = false;
      // FastAPI retourne detail comme array ou string
      const detail = err.error?.detail;
      if (Array.isArray(detail)) {
        this.error = detail.map((d: any) => `${d.loc?.join('.')}: ${d.msg}`).join(' | ');
      } else if (typeof detail === 'string') {
        this.error = detail;
      } else {
        this.error = 'Erreur lors de la sauvegarde.';
      }
      this.cdr.detectChanges();
    }
  });
}

  confirmDelete() {
  if (!this.canDeleteInvoice) {
    return;
  }

  Swal.fire({
    title: 'Supprimer la facture ?',
    text: `Facture ${this.invoice.numero_facture} — Cette action est irréversible.`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    cancelButtonColor: '#6b7280',
    confirmButtonText: '🗑️ Oui, supprimer',
    cancelButtonText: 'Annuler',
  }).then((result) => {
    if (result.isConfirmed) {
      this.deleting = true;
      this.cdr.detectChanges();
      this.invoiceService.deleteInvoice(this.invoiceId).subscribe({
        next: () => {
          Swal.fire({
            title: 'Supprimée !',
            text: 'La facture a été supprimée avec succès.',
            icon: 'success',
            confirmButtonColor: '#6366f1',
            timer: 2000,
            timerProgressBar: true,
          }).then(() => {
            this.router.navigate(['/invoices']);
          });
        },
        error: () => {
          this.deleting = false;
          this.cdr.detectChanges();
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

  goBack() {
    this.router.navigate(['/invoices']);
  }
  onMouseMove(event: MouseEvent) {
  const el = event.currentTarget as HTMLElement;
  const rect = el.getBoundingClientRect();
  this.zoomX = ((event.clientX - rect.left) / rect.width)  * 100;
  this.zoomY = ((event.clientY - rect.top)  / rect.height) * 100;
  this.cdr.detectChanges();
}

openFullscreen() {
  this.fullscreen = true;
  this.cdr.detectChanges();
}
}