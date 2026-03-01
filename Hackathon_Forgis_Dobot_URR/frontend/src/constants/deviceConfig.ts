import { Activity, Bot, Eye, Hand } from "lucide-react";
import type { DeviceType, DeviceStatus, Device } from "@/types";

// ── Icon mapping ─────────────────────────────────────────────

export const DEVICE_ICONS: Record<DeviceType, React.ComponentType<{ className?: string }>> = {
  robot: Bot,
  camera: Eye,
  sensor: Activity,
  gripper: Hand,
};

// ── Status display ───────────────────────────────────────────

export const STATUS_COLOR: Record<DeviceStatus, string> = {
  connected: "var(--status-healthy)",
  warning: "var(--orange)",
  disconnected: "var(--status-critical)",
};

export const STATUS_LABEL: Record<DeviceStatus, string> = {
  connected: "Connected",
  warning: "Warning",
  disconnected: "Offline",
};

// ── Vendor brands per device type ────────────────────────────

export const BRANDS: Record<DeviceType, string[]> = {
  robot: ["Universal Robots", "ABB", "KUKA", "Fanuc", "Yaskawa", "Doosan"],
  camera: ["Logitech", "Intel RealSense", "Cognex", "Keyence", "Basler", "Sick", "Allied Vision"],
  sensor: ["Sick", "Pepperl+Fuchs", "Banner Engineering", "ifm", "Balluff"],
  gripper: ["OnRobot", "Robotiq", "Schunk", "SMC", "Zimmer Group"],
};

// ── Default devices (pre-populated) ─────────────────────────

export const DEFAULT_DEVICES: Device[] = [
  {
    id: "robot-default",
    name: "UR3",
    vendor: "Universal Robots",
    type: "robot",
    status: "disconnected",
    ip: "192.168.163.11",
    reachable: false,
    onlineSince: "2024-02-20T10:00:00Z",
    firmwareVersion: "5.11.0",
  },
  {
    id: "cam-default",
    name: "USB Camera",
    vendor: "Logitech",
    type: "camera",
    status: "disconnected",
    ip: "/dev/video0",
    reachable: false,
    onlineSince: "2024-02-21T08:30:00Z",
    firmwareVersion: "UVC",
  },
  {
    id: "gripper-default",
    name: "RG2 Gripper",
    vendor: "OnRobot",
    type: "gripper",
    status: "disconnected",
    ip: "192.168.0.103",
    reachable: false,
    onlineSince: "2024-02-22T09:15:00Z",
    firmwareVersion: "1.2.3",
  },
];

// ── Add-device form state ────────────────────────────────────

export interface DeviceFormData {
  type: DeviceType | "";
  brand: string;
  robotModel: string;
  name: string;
  apiEndpoint: string;
  firmwareVersion: string;
  lastMaintenance: string;
}

export const EMPTY_FORM: DeviceFormData = {
  type: "",
  brand: "",
  robotModel: "",
  name: "",
  apiEndpoint: "",
  firmwareVersion: "",
  lastMaintenance: "",
};
