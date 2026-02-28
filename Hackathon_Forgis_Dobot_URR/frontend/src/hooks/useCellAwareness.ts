import { useState, useCallback, useRef, useEffect } from "react";
import { inferCellState, type CellStateSummary } from "@/api/cellApi";

export function useCellAwareness(cameraFrame: string | null, active: boolean = true) {
    const [summary, setSummary] = useState<CellStateSummary | null>(null);
    const [loading, setLoading] = useState(false);
    const lastInferenceTime = useRef<number>(0);
    const INFERENCE_INTERVAL = 10000; // 10 seconds

    const runInference = useCallback(async () => {
        if (!cameraFrame || loading || !active) return;

        const now = Date.now();
        if (now - lastInferenceTime.current < INFERENCE_INTERVAL) return;

        setLoading(true);
        try {
            // Convert base64 to blob
            const base64Data = cameraFrame.split(",")[1];
            const byteCharacters = atob(base64Data);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: "image/jpeg" });

            const result = await inferCellState(blob);
            setSummary(result);
            lastInferenceTime.current = Date.now();
        } catch (error) {
            console.error("Cell state inference failed:", error);
        } finally {
            setLoading(false);
        }
    }, [cameraFrame, loading, active]);

    useEffect(() => {
        if (active && cameraFrame) {
            const timer = setTimeout(runInference, 2000); // Initial delay
            return () => clearTimeout(timer);
        }
    }, [cameraFrame, active, runInference]);

    return { summary, loading, runInference };
}
