export interface CellStateSummary {
    state: string;
    active_objects: string[];
    anomalies: string[];
    safety_status: 'Clear' | 'Warning' | 'Hazard';
    confidence: number;
}

export async function inferCellState(imageBlob: Blob, context?: string): Promise<CellStateSummary> {
    const formData = new FormData();
    formData.append('image', imageBlob, 'cell_frame.jpg');
    if (context) {
        formData.append('context', context);
    }

    const response = await fetch('/api/cell/infer-state', {
        method: 'POST',
        body: formData,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || `Inference failed: ${response.statusText}`);
    }

    return response.json();
}
