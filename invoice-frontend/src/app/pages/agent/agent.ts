import { Component, ChangeDetectorRef, NgZone } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { AgentService } from '../../services/agent';

interface Message {
  role: 'user' | 'agent';
  content: string;
  sql?: string;
  timestamp: Date;
  rating?: 'up' | 'down' | null;
  sqlRows?: any[];
  pdfBase64?: string;
  pdfFilename?: string;
}

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './agent.html',
  styleUrls: ['./agent.css']
})
export class AgentComponent {
  messages: Message[] = [];
  question     = '';
  loading      = false;
  showSql      = false;
  copiedIndex  = -1;
  isListening  = false;
  micError     = '';
  recognition: any = null;
  private sessionId = this.newSessionId();

  suggestions = [
    'Donne moi toutes les factures disponibles',
    'Quelle est la facture avec le montant TTC le plus élevé ?',
    'Liste les factures du vendeur TOPNET',
    'Quel est le total TTC de toutes les factures ?',
  ];

  constructor(
    private agentService: AgentService,
    private cdr:  ChangeDetectorRef,
    private ngZone: NgZone,
    private sanitizer: DomSanitizer,
    
   
  ) {
    this.messages.push({
      role:      'agent',
      content:   'Bonjour ! Je suis votre assistant IA pour l\'analyse de factures UNILOG. Posez-moi une question sur vos factures.',
      timestamp: new Date()
    });
    this.initSpeechRecognition();
  }

  private newSessionId(): string {
    const rand = Math.random().toString(36).slice(2, 10);
    return `agent-${Date.now()}-${rand}`;
  }

  initSpeechRecognition() {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      this.micError = 'Reconnaissance vocale non supportée par ce navigateur.';
      return;
    }
    this.recognition = new SpeechRecognition();
    this.recognition.lang = 'fr-FR';
    this.recognition.continuous = false;
    this.recognition.interimResults = false;

    this.recognition.onresult = (event: any) => {
      this.ngZone.run(() => {
        
        this.question    = event.results[0][0].transcript;
        this.isListening = false;
        this.cdr.detectChanges();
      });
    };
    this.recognition.onerror = (event: any) => {
      this.ngZone.run(() => {
        this.micError    = `Erreur microphone : ${event.error}`;
        this.isListening = false;
        this.cdr.detectChanges();
      });
    };
    this.recognition.onend = () => {
      this.ngZone.run(() => {
        this.isListening = false;
        this.cdr.detectChanges();
      });
    };
  }
loadingStep     = 'L\'agent réfléchit...';
private stepTimer: any[] = [];
private startLoadingSteps() {
  this.loadingStep      = 'L\'agent réfléchit...';

  // Clear any existing timers
  if (this.stepTimer) {
    this.stepTimer.forEach((t: any) => clearTimeout(t));
  }
}

private stopLoadingSteps() {
  // Clear all pending timers
  if (this.stepTimer) {
    this.stepTimer.forEach((t: any) => clearTimeout(t));
    this.stepTimer = [];
  }
}
  toggleMic() {
    if (!this.recognition) return;
    this.micError = '';
    if (this.isListening) {
      this.recognition.stop();
      this.isListening = false;
    } else {
      this.recognition.start();
      this.isListening = true;
    }
    this.cdr.detectChanges();
  }

  copyMessage(text: string, index: number) {
    navigator.clipboard.writeText(text).then(() => {
      this.ngZone.run(() => {
        this.copiedIndex = index;
        this.cdr.detectChanges();
        setTimeout(() => {
          this.copiedIndex = -1;
          this.cdr.detectChanges();
        }, 2000);
      });
    });
  }

  private downloadPdfFromBase64(base64Data: string, filename: string) {
    try {
      const binary = atob(base64Data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'invoice_recap.pdf';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // Keep chat responsive even if browser blocks/decoding fails.
    }
  }

  downloadMessagePdf(msg: Message) {
    if (!msg.pdfBase64) return;
    this.downloadPdfFromBase64(msg.pdfBase64, msg.pdfFilename || 'invoice_recap.pdf');
  }

  // ── Évaluation ────────────────────────────────────────────
  rateMessage(index: number, rating: 'up' | 'down') {
    if (this.messages[index].rating) return;
    this.messages[index].rating = rating;
    this.cdr.detectChanges();
  }

  // ── Colonnes tableau ──────────────────────────────────────
  getColumns(rows: any[]): string[] {
    if (!rows || rows.length === 0) return [];
    return Object.keys(rows[0]);
  }

  displayCell(value: any): string {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value);
      } catch {
        return String(value);
      }
    }
    return String(value);
  }

  private formatAmountValue(value: any): string {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value.toFixed(3) : '—';
    }
    const parsed = Number(String(value).trim().replace(',', '.'));
    return Number.isFinite(parsed) ? parsed.toFixed(3) : String(value);
  }

  // ── Format lignes réponse ─────────────────────────────────
formatHtml(content: string): SafeHtml {
  if (!content) return '';
  const lines  = content.split('\n').map(l => l.trim());
  let html     = '';
  let cardFields: { key: string; val: string }[] = [];

  const flushCard = () => {
    if (cardFields.length > 0) {
      html += this.buildCard(cardFields);
      cardFields = [];
    }
  };

  let idx = 0;
  while (idx < lines.length) {
    const line = lines[idx];

    // ── Empty line → flush current card
    if (!line) {
      flushCard();
      idx += 1;
      continue;
    }

    // Markdown headings (e.g., ### Details)
    if (/^#{1,6}\s+/.test(line)) {
      flushCard();
      const title = line.replace(/^#{1,6}\s+/, '');
      html += `
        <p style="margin:8px 0 6px 0;font-size:13px;font-weight:700;color:#4c1d95;">
          ${this.parseBold(title)}
        </p>`;
      idx += 1;
      continue;
    }

    // Markdown table block
    if (this.isMarkdownTableLine(line)) {
      const block: string[] = [];
      while (idx < lines.length && this.isMarkdownTableLine(lines[idx])) {
        block.push(lines[idx]);
        idx += 1;
      }
      if (block.length >= 2 && this.isMarkdownSeparatorLine(block[1])) {
        flushCard();
        html += this.renderMarkdownTable(block);
        continue;
      }
      // Not a valid markdown table, render raw lines.
      flushCard();
      html += block
        .map((b) => `
        <p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:inherit;">
          ${this.parseBold(b)}
        </p>`)
        .join('');
      continue;
    }

    // ── Remove optional leading "- " prefix
    const cleaned = line.replace(/^-\s*/, '').trim();

    // ── Check if line is "Key : Value" format (colon within first 40 chars)
    const colonIdx = cleaned.indexOf(' :');
    if (colonIdx !== -1 && colonIdx < 40) {
      const key = cleaned.substring(0, colonIdx).trim();
      const val = cleaned.substring(colonIdx + 2).trim();

      // New invoice starts → flush previous card first
      if (key.toLowerCase() === 'facture numéro' && cardFields.length > 0) {
        flushCard();
      }

      // Skip null/empty values entirely
      if (!val || val === 'None' || val === 'null' || val === '—' || val === '-') {
        idx += 1;
        continue;
      }

      cardFields.push({ key, val });
      idx += 1;
      continue;
    }

    // ── Plain text line → flush card first
    flushCard();

    // "Total : X facture(s)" → styled summary box
    if (/^total\s*:/i.test(cleaned)) {
      html += `
        <div style="margin:10px 0 4px 0;padding:8px 14px;
                    background:rgba(124,58,237,0.06);
                    border-left:3px solid #7c3aed;
                    border-radius:0 8px 8px 0;
                    font-size:13px;font-weight:600;color:#6d28d9;">
          ${this.parseBold(cleaned)}
        </div>`;
    } else {
      html += `
        <p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:inherit;">
          ${this.parseBold(cleaned)}
        </p>`;
    }
    idx += 1;
  }

  // flush last card if any
  flushCard();

  return this.sanitizer.bypassSecurityTrustHtml(html);
}

private isMarkdownTableLine(line: string): boolean {
  return line.startsWith('|') && line.endsWith('|') && line.includes('|');
}

private isMarkdownSeparatorLine(line: string): boolean {
  const compact = line.replace(/\s+/g, '');
  return /^\|?[:\-\|]+\|?$/.test(compact);
}

private renderMarkdownTable(lines: string[]): string {
  const toCells = (row: string): string[] =>
    row
      .split('|')
      .slice(1, -1)
      .map((c) => c.trim());

  const header = toCells(lines[0]);
  const bodyRows = lines.slice(2).map(toCells).filter((r) => r.length > 0);

  const headHtml = header
    .map(
      (h) =>
        `<th style="padding:6px 10px;text-align:left;font-size:11px;font-weight:700;color:#6b7280;border-bottom:1px solid #e5e7eb;">${this.parseBold(h || '—')}</th>`
    )
    .join('');

  const bodyHtml = bodyRows
    .map((row) => {
      const cells = row
        .map(
          (c) =>
            `<td style="padding:6px 10px;font-size:12px;color:#374151;border-bottom:1px solid #f3f4f6;vertical-align:top;">${this.parseBold(c || '—')}</td>`
        )
        .join('');
      return `<tr>${cells}</tr>`;
    })
    .join('');

  return `
    <div style="overflow-x:auto;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;">
      <table style="width:100%;border-collapse:collapse;background:white;">
        <thead style="background:#f9fafb;"><tr>${headHtml}</tr></thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>`;
}

private buildCard(fields: { key: string; val: string }[]): string {
  const rows = fields.map(({ key, val }) => {
    let valHtml = this.parseBold(val);

    if (key === 'Statut de paiement') {
      const color = /réglé/i.test(val)   ? '#10b981'
                  : /retard/i.test(val)   ? '#ef4444'
                  : /attente/i.test(val)  ? '#f59e0b'
                  : '#9ca3af';
      valHtml = `<span style="display:inline-block;background:${color}18;color:${color};
                   border:1px solid ${color}33;border-radius:20px;padding:1px 10px;
                   font-size:11px;font-weight:600;">${val}</span>`;
    }

    return `
      <div style="display:flex;align-items:baseline;gap:12px;padding:4px 0;
                  font-size:12.5px;border-bottom:1px solid rgba(124,58,237,0.07);">
        <span style="color:#7c3aed;font-weight:600;white-space:nowrap;
                     min-width:155px;flex-shrink:0;font-size:11.5px;">${key}</span>
        <span style="color:inherit;word-break:break-word;">${valHtml}</span>
      </div>`;
  }).join('');

  return `
    <div style="border:1px solid rgba(124,58,237,0.15);border-left:3px solid #7c3aed;
                border-radius:0 10px 10px 0;padding:10px 14px;margin:8px 0;
                background:rgba(124,58,237,0.025);">${rows}</div>`;
}




private parseBold(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  return escaped.replace(/\*\*(.*?)\*\*/g, '<strong style="font-weight:600;color:#6d28d9;">$1</strong>');
}

  private mapResultsToRows(results: any[]): any[] {
    return (results || []).map((doc: any) => {
      const invoice = doc?.invoice || {};
      const facture = invoice?.facture || {};
      const vendeur = invoice?.vendeur || {};
      const client = invoice?.client || {};
      const totaux = invoice?.totaux || {};
      const paiement = invoice?.paiement || {};

      if (!invoice || typeof invoice !== 'object' || Object.keys(invoice).length === 0) {
        return doc;
      }

      return {
        numero_facture: facture.numero || '—',
        vendeur: vendeur.nom || '—',
        client: client.nom || '—',
        date: facture.date || '—',
        total_ttc: this.formatAmountValue(totaux.total_ttc),
        devise: totaux.devise || '—',
        statut: paiement.statu_paiement || paiement.statut_paiement || '—',
      };
    });
  }

  // ── Historique conversationnel ────────────────────────────
  private buildHistory(): { question: string; answer: string }[] {
    const history: { question: string; answer: string }[] = [];
    for (let i = 0; i < this.messages.length - 1; i++) {
      if (this.messages[i].role === 'user' && this.messages[i + 1]?.role === 'agent') {
        history.push({
          question: this.messages[i].content,
          answer:   this.messages[i + 1].content
        });
      }
    }
    return history.slice(-5);
  }

 ask() {
  if (!this.question.trim() || this.loading) return;
  const q       = this.question.trim();
  this.question = '';
  this.loading  = true;
  this.startLoadingSteps(); // 🔁 add this
  this.messages.push({ role: 'user', content: q, timestamp: new Date() });
  this.cdr.detectChanges();
  setTimeout(() => this.scrollToBottom(), 100);

  this.agentService.ask(q, this.sessionId).subscribe({
    next: (res) => {
      this.ngZone.run(() => {
        this.stopLoadingSteps(); // 🔁 add this
        this.messages.push({
          role:      'agent',
          content:   res.answer || 'Aucune réponse reçue.',
          sql:       res.mongo_filter ? JSON.stringify(res.mongo_filter) : '',
          sqlRows:   [],
          pdfBase64: res.pdf_base64 || '',
          pdfFilename: res.pdf_filename || 'invoice_recap.pdf',
          timestamp: new Date(),
          rating:    null
        });
        if (res.pdf_generated && res.pdf_base64) {
          this.downloadPdfFromBase64(res.pdf_base64, res.pdf_filename || 'invoice_recap.pdf');
        }
        this.loading = false;
        this.cdr.detectChanges();
        setTimeout(() => {
          this.scrollToBottom();
          this.cdr.detectChanges();
        }, 100);
      });
    },
    error: (err: HttpErrorResponse) => {
      this.ngZone.run(() => {
        const backendDetail = (err?.error?.detail || err?.error?.message || '').toString().trim();
        const message = err?.status === 403
          ? (backendDetail || 'Permission refusée : vous n\'avez pas l\'autorisation d\'utiliser le chat.')
          : (backendDetail || 'Désolé, une erreur s\'est produite. Veuillez réessayer.');

        this.stopLoadingSteps(); // 🔁 add this
        this.messages.push({
          role:      'agent',
          content:   message,
          timestamp: new Date()
        });
        this.loading = false;
        this.cdr.detectChanges();
      });
    }
  });
}



  useSuggestion(s: string) {
    this.question = s;
    this.ask();
  }

  scrollToBottom() {
    const el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
  }

  onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.ask();
    }
  }

  clearChat() {
    this.sessionId = this.newSessionId();
    this.messages = [{
      role:      'agent',
      content:   'Conversation réinitialisée. Comment puis-je vous aider ?',
      timestamp: new Date()
    }];
    this.cdr.detectChanges();
  }
}