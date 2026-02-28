import { getJson, postJson } from "./httpClient";

export interface DeviceStatus {
    status: "connected" | "warning" | "disconnected";
    error?: string;
    suggestion?: string;
}

export interface OverallHealth {
    overall_status: "healthy" | "degraded";
    devices: Record<string, DeviceStatus>;
}

export interface RetryResponse {
    success: boolean;
    message: string;
}

export async function getOverallHealth(): Promise<OverallHealth> {
    return getJson<OverallHealth>("/health");
}

export async function retryInitialisation(deviceName?: string): Promise<RetryResponse> {
    return postJson<RetryResponse>("/health/retry", { device_name: deviceName });
}
