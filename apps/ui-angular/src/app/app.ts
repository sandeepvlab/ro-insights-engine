import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';

interface RepairOrderSummary {
  ro_id: string;
  file: string;
}

interface Opportunity {
  type: string;
  finding: string;
  current_rate?: number;
  reference_rate?: number;
  potential_additional_labor?: number;
}

interface AnalysisResult {
  ro_id: string;
  run_id: string;
  damage_classification: {
    category: string;
    sub_category: string;
    severity: string;
    confidence: number;
  };
  opportunities: Opportunity[];
  status: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private apiBase = 'http://localhost:8000';

  repairOrders = signal<RepairOrderSummary[]>([]);
  selectedRoId = signal<string | null>(null);
  result = signal<AnalysisResult | null>(null);
  loading = signal<boolean>(false);
  error = signal<string | null>(null);

  constructor(private http: HttpClient) {
    this.loadRepairOrders();
  }

  loadRepairOrders() {
    this.http.get<{ repair_orders: RepairOrderSummary[] }>(`${this.apiBase}/ro/list`)
      .subscribe({
        next: (res) => this.repairOrders.set(res.repair_orders),
        error: (err) => this.error.set('Failed to load repair orders. Is the API running on port 8000?'),
      });
  }

  analyze(roId: string) {
    this.selectedRoId.set(roId);
    this.result.set(null);
    this.error.set(null);
    this.loading.set(true);

    this.http.post<AnalysisResult>(`${this.apiBase}/ro/${roId}/analyze`, {})
      .subscribe({
        next: (res) => {
          this.result.set(res);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set('Analysis failed: ' + (err?.error?.detail || err.message));
          this.loading.set(false);
        },
      });
  }
}
