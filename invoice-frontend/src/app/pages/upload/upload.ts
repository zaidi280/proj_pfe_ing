import { Component, ChangeDetectorRef, NgZone, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { InvoiceService } from '../../services/invoice';
import { catchError, forkJoin, of } from 'rxjs';

@Component({
  selector: 'app-upload',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule],
  templateUrl: './upload.html',
  styleUrls: ['./upload.css']
})
export class UploadComponent implements OnInit {
  step: 'upload' | 'list' | 'form' | 'success' = 'upload';
  loading    = false;
  error      = '';
  saveWarning = '';
  extractedItems: any[] = [];
  selectedFiles: File[] = [];
  selectedFile: File | null = null;
  previewUrls: string[] = [];
  previewUrl: string | null = null;
  formData: any  = null;
  extractionId   = '';
  batchId        = '';
  sourceFile     = '';
  imagePath      = '';
  
  // Pagination
  currentPage = 1;
  itemsPerPage = 10;
  totalPages = 1;
  
  // Math reference for template
  Math = Math;

  constructor(
    private invoiceService: InvoiceService,
    private cdr: ChangeDetectorRef,
    private ngZone: NgZone
  ) {}

  ngOnInit() {
    this.loadExistingExtractions();
  }

  get paginatedItems(): any[] {
    const startIndex = (this.currentPage - 1) * this.itemsPerPage;
    const endIndex = startIndex + this.itemsPerPage;
    return this.extractedItems.slice(startIndex, endIndex);
  }

  get totalPages_computed(): number {
    return Math.max(1, Math.ceil(this.extractedItems.length / this.itemsPerPage));
  }

  get pageNumbers(): number[] {
    const total = this.totalPages_computed;
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  goToPage(page: number) {
    const max = this.totalPages_computed;
    if (page < 1 || page > max) return;
    this.ngZone.run(() => {
      this.currentPage = page;
      this.cdr.detectChanges();
    });
  }

  nextPage() {
    this.goToPage(this.currentPage + 1);
  }

  prevPage() {
    this.goToPage(this.currentPage - 1);
  }

  onFileSelected(event: any) {
    const files = Array.from(event?.target?.files || []) as File[];
    if (!files.length) return;
    this.setSelectedFiles(files, true);

    // Reset input value so selecting the same file again still triggers change.
    if (event?.target) {
      event.target.value = '';
    }
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    const files = Array.from(event.dataTransfer?.files || []) as File[];
    if (!files.length) return;
    this.setSelectedFiles(files, true);
  }

  onDragOver(event: DragEvent) { event.preventDefault(); }

  goToExtractionList() {
    if (!this.extractedItems.length) return;
    this.ngZone.run(() => {
      this.step = 'list';
      this.cdr.detectChanges();
    });
  }

  removeSelectedFile(index: number) {
    if (index < 0 || index >= this.selectedFiles.length) return;

    this.ngZone.run(() => {
      const url = this.previewUrls[index];
      if (url) {
        URL.revokeObjectURL(url);
      }

      this.selectedFiles.splice(index, 1);
      this.previewUrls.splice(index, 1);

      this.selectedFile = this.selectedFiles[0] || null;
      this.previewUrl = this.previewUrls[0] || null;

      this.cdr.detectChanges();
    });
  }

  uploadAndExtract() {
    if (!this.selectedFiles.length) return;
    this.ngZone.run(() => {
      this.loading = true;
      this.error   = '';
      this.cdr.detectChanges();
    });
    this.invoiceService.extractInvoices(this.selectedFiles).subscribe({
      next: (res) => {
        this.ngZone.run(() => {
          const items = Array.isArray(res?.items) ? res.items : [];
          if (!items.length) {
            this.error = 'Extraction invalide: aucune facture retournee.';
            this.loading = false;
            this.cdr.detectChanges();
            return;
          }

          this.batchId = res?.batch_id || '';
          const existing = new Map(this.extractedItems.map((item) => [item?.extraction_id, item]));
          for (const item of items) {
            if (!item?.extraction_id) continue;
            existing.set(item.extraction_id, item);
          }
          this.extractedItems = Array.from(existing.values());
          this.currentPage = 1;
          this.loading    = false;
          this.step       = 'list';
          this.cdr.detectChanges();
        });
      },
      error: (err) => {
        this.ngZone.run(() => {
          this.error = this.toErrorMessage(err, 'Erreur lors de l\'extraction.');
          this.loading = false;
          this.cdr.detectChanges();
        });
      }
    });
  }

  addLigne() {
    if (!this.formData?.lignes) {
      this.formData = this.formData || {};
      this.formData.lignes = [];
    }
    this.formData.lignes.push({
      designation: '', code_article: null,
      quantite: 1, unite: null,
      prix_unitaire_ht: null, remise_pct: 0,
      montant_ht: null, taux_tva: null
    });
    this.cdr.detectChanges();
  }

  removeLigne(index: number) {
    this.formData.lignes.splice(index, 1);
    this.cdr.detectChanges();
  }

  openExtraction(item: any) {
    if (!item?.extraction_id) {
      this.error = 'Extraction invalide.';
      return;
    }

    this.ngZone.run(() => {
      this.error = '';
      this.extractionId = item.extraction_id;
      this.formData = this.toFormData(item.invoice || {});
      this.sourceFile = item.filename || '';
      this.imagePath = '';
      this.step = 'form';
      this.cdr.detectChanges();
    });
  }

  backToList() {
    this.ngZone.run(() => {
      this.step = 'list';
      this.cdr.detectChanges();
    });
  }

  confirmAndSave() {
    if (!this.extractionId) {
      this.error = 'Erreur: extraction_id manquant.';
      return;
    }

    this.ngZone.run(() => {
      this.loading = true;
      this.error   = '';
      this.cdr.detectChanges();
    });

    const payload = this.toInvoicePayload(this.formData || {});

    this.invoiceService.saveInvoice(payload, this.extractionId).subscribe({
      next: (res) => {
        this.ngZone.run(() => {
          if (this.extractionId) {
            this.extractedItems = this.extractedItems.filter(
              (item) => item?.extraction_id !== this.extractionId
            );
          }
          this.saveWarning = res?.extraction_deleted === false
            ? 'Attention: la facture est sauvegardee, mais le brouillon temporaire n\'a pas ete supprime.'
            : '';
          this.step    = 'success';
          this.loading = false;
          this.cdr.detectChanges();
        });
      },
      error: (err) => {
        this.ngZone.run(() => {
          this.error = this.toErrorMessage(err, 'Erreur lors de la sauvegarde.');
          this.loading = false;
          this.cdr.detectChanges();
        });
      }
    });
  }

  continueWithOtherExtractions() {
    this.ngZone.run(() => {
      if (this.extractionId) {
        this.extractedItems = this.extractedItems.filter((item) => item?.extraction_id !== this.extractionId);
      }

      this.formData = null;
      this.extractionId = '';
      this.sourceFile = '';
      this.imagePath = '';
      this.error = '';
      this.saveWarning = '';

      this.step = this.extractedItems.length ? 'list' : 'upload';
      this.cdr.detectChanges();
    });
  }

  reset() {
    this.ngZone.run(() => {
      this.step         = 'upload';
      this.selectedFiles = [];
      this.selectedFile = null;
      this.clearPreviewUrls();
      this.previewUrl   = null;
      this.formData     = null;
      this.extractionId = '';
      this.batchId      = '';
      this.sourceFile   = '';
      this.imagePath    = '';
      this.error        = '';
      this.saveWarning  = '';
      this.cdr.detectChanges();
    });
  }

  removeExtraction(item: any) {
    const id = item?.extraction_id;
    if (!id) return;

    this.invoiceService.deleteExtraction(id).subscribe({
      next: () => {
        this.ngZone.run(() => {
          this.extractedItems = this.extractedItems.filter((it) => it?.extraction_id !== id);
          if (this.extractionId === id) {
            this.formData = null;
            this.extractionId = '';
            this.sourceFile = '';
            this.imagePath = '';
          }
          if (this.currentPage > this.totalPages_computed) {
            this.currentPage = Math.max(1, this.totalPages_computed);
          }
          if (this.step === 'list' && !this.extractedItems.length) {
            this.step = 'upload';
          }
          this.cdr.detectChanges();
        });
      },
      error: (err) => {
        this.ngZone.run(() => {
          this.error = this.toErrorMessage(err, 'Suppression impossible.');
          this.cdr.detectChanges();
        });
      },
    });
  }

  clearExtractions() {
    const ids = this.extractedItems
      .map((item) => item?.extraction_id)
      .filter((id): id is string => typeof id === 'string' && !!id.trim());

    if (!ids.length) {
      this.ngZone.run(() => {
        this.extractedItems = [];
        if (this.step === 'list') {
          this.step = 'upload';
        }
        this.cdr.detectChanges();
      });
      return;
    }

    this.ngZone.run(() => {
      this.loading = true;
      this.error = '';
      this.cdr.detectChanges();
    });

    const deletions = ids.map((id) =>
      this.invoiceService.deleteExtraction(id).pipe(catchError(() => of(null)))
    );

    forkJoin(deletions).subscribe({
      next: () => {
        this.ngZone.run(() => {
          this.extractedItems = [];
          this.currentPage = 1;
          if (this.step === 'list') {
            this.step = 'upload';
          }
          this.loading = false;
          this.cdr.detectChanges();
        });
      },
      error: (err) => {
        this.ngZone.run(() => {
          this.error = this.toErrorMessage(err, 'Suppression impossible.');
          this.loading = false;
          this.cdr.detectChanges();
        });
      },
    });
  }

  private setSelectedFiles(files: File[], append = false) {
    this.ngZone.run(() => {
      const mergedFiles = append ? this.mergeUniqueFiles(this.selectedFiles, files) : files;

      this.clearPreviewUrls();
      this.selectedFiles = mergedFiles;
      this.selectedFile = this.selectedFiles[0] || null;
      this.error = '';
      this.previewUrls = this.selectedFiles.map((file) => URL.createObjectURL(file));
      this.previewUrl = this.previewUrls[0] || null;
      this.cdr.detectChanges();
    });
  }

  private mergeUniqueFiles(existing: File[], incoming: File[]): File[] {
    const seen = new Set(existing.map((f) => `${f.name}::${f.size}::${f.lastModified}`));
    const out = [...existing];

    for (const file of incoming) {
      const key = `${file.name}::${file.size}::${file.lastModified}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(file);
    }

    return out;
  }

  private clearPreviewUrls() {
    for (const url of this.previewUrls) {
      URL.revokeObjectURL(url);
    }
    this.previewUrls = [];
  }

  private formatAmountValue(value: any): string {
    if (value === null || value === undefined || value === '') {
      return '';
    }

    if (typeof value === 'number') {
      return Number.isFinite(value) ? value.toFixed(3) : '';
    }

    const parsed = Number(String(value).trim().replace(',', '.'));
    return Number.isFinite(parsed) ? parsed.toFixed(3) : String(value).trim();
  }

  private toFormData(invoice: any): any {
    const vendeur = invoice?.vendeur || {};
    const client = invoice?.client || {};
    const facture = invoice?.facture || {};
    const totaux = invoice?.totaux || {};
    const paiement = invoice?.paiement || {};
    const lignes = Array.isArray(invoice?.lignes) ? invoice.lignes : [];

    return {
      numero_facture: facture?.numero || '',
      type_document: facture?.type || 'FACTURE',
      date_facture: facture?.date || '',
      date_echeance: facture?.date_echeance || '',

      vendeur_nom: vendeur?.nom || '',
      vendeur_mf: vendeur?.matricule_fiscale || '',
      vendeur_adresse: vendeur?.adresse || '',
      vendeur_telephone: vendeur?.telephone || '',
      vendeur_email: vendeur?.email || '',

      client_nom: client?.nom || '',
      client_mf: client?.matricule_fiscale || '',
      client_adresse: client?.adresse || '',

      total_ht: this.formatAmountValue(totaux?.total_ht),
      montant_tva: this.formatAmountValue(totaux?.total_tva),
      timbre_fiscal: this.formatAmountValue(totaux?.timbre_fiscal),
      total_ttc: this.formatAmountValue(totaux?.total_ttc),
      devise: totaux?.devise || 'DT',

      montant_en_lettres: paiement?.montant_en_lettres || '',
      mode_paiement: paiement?.mode_paiement || '',
      statut_paiement: paiement?.statu_paiement || paiement?.statut_paiement || '',
      conditions_paiement: paiement?.conditions_paiement || '',
      date_reglement: paiement?.date_reglement || '',

      lignes: lignes.map((ligne: any) => ({
        designation: ligne?.designation || '',
        code_article: ligne?.code_article || '',
        quantite: ligne?.quantite ?? '',
        unite: ligne?.unite ?? '',
        prix_unitaire_ht: this.formatAmountValue(ligne?.prix_unitaire_ht),
        remise_pct: this.formatAmountValue(ligne?.remise ?? ligne?.remise_pct),
        montant_ht: this.formatAmountValue(ligne?.montant_ht),
        taux_tva: ligne?.taux_tva ?? '',
      })),
    };
  }

  private toInvoicePayload(form: any): any {
    const lignes = Array.isArray(form?.lignes) ? form.lignes : [];

    return {
      vendeur: {
        nom: form?.vendeur_nom || '',
        adresse: form?.vendeur_adresse || '',
        telephone: form?.vendeur_telephone || '',
        email: form?.vendeur_email || '',
        matricule_fiscale: form?.vendeur_mf || '',
      },
      client: {
        nom: form?.client_nom || '',
        adresse: form?.client_adresse || '',
        matricule_fiscale: form?.client_mf || '',
      },
      facture: {
        numero: form?.numero_facture || '',
        date: form?.date_facture || '',
        date_echeance: form?.date_echeance || '',
        type: form?.type_document || '',
      },
      lignes: lignes.map((ligne: any) => ({
        quantite: ligne?.quantite ?? '',
        unite: ligne?.unite ?? '',
        code_article: ligne?.code_article ?? '',
        designation: ligne?.designation ?? '',
        prix_unitaire_ht: ligne?.prix_unitaire_ht ?? '',
        taux_tva: ligne?.taux_tva ?? '',
        montant_ht: ligne?.montant_ht ?? '',
        remise: ligne?.remise_pct ?? '',
      })),
      totaux: {
        total_ht: form?.total_ht ?? '',
        total_tva: form?.montant_tva ?? '',
        timbre_fiscal: form?.timbre_fiscal ?? '',
        total_ttc: form?.total_ttc ?? '',
        devise: form?.devise ?? '',
      },
      paiement: {
        montant_en_lettres: form?.montant_en_lettres ?? '',
        mode_paiement: form?.mode_paiement ?? '',
        statu_paiement: form?.statut_paiement ?? '',
        conditions_paiement: form?.conditions_paiement ?? '',
        date_reglement: form?.date_reglement ?? '',
      },
      fichier: {
        _source_file: this.sourceFile || '',
        image_path: this.imagePath || '',
      },
    };
  }

  private toErrorMessage(err: any, fallback: string): string {
    const detail = err?.error?.detail;
    if (Array.isArray(detail)) {
      return detail.map((e: any) => e?.msg || JSON.stringify(e)).join(' | ');
    }
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    return fallback;
  }

  private loadExistingExtractions() {
    this.invoiceService.listExtractions().subscribe({
      next: (res) => {
        this.ngZone.run(() => {
          const items = Array.isArray(res?.items) ? res.items : [];
          this.extractedItems = items;
          this.cdr.detectChanges();
        });
      },
      error: () => {
        // Keep upload page usable even if list fetch fails.
      },
    });
  }
}