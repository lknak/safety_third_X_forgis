import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import type { Device, SelectedStep } from "@/types";
import { DEFAULT_DEVICES } from "@/constants/deviceConfig";
import { getOverallHealth } from "@/api/healthApi";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DeviceList } from "./DeviceList";
import { AddDeviceDialog } from "./AddDeviceDialog";
import { NodeCreatorDialog } from "./NodeCreatorDialog";
import { ParameterEditor } from "./ParameterEditor";

interface DevicesSidebarProps {
  selectedStep?: SelectedStep | null;
  onDeselectStep?: () => void;
  onParamChange?: (nodeId: string, stepId: string, key: string, value: unknown) => void;
  nodeCreatorOpen?: boolean;
  onCloseNodeCreator?: () => void;
  onOpenDeviceDetail?: (device: Device) => void;
}

export function DevicesSidebar({ selectedStep, onDeselectStep, onParamChange, nodeCreatorOpen, onCloseNodeCreator, onOpenDeviceDetail }: DevicesSidebarProps) {
  const [devices, setDevices] = useState<Device[]>(DEFAULT_DEVICES);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);

  useEffect(() => {
    if (devices.length === 0) {
      setSelectedDeviceId(null);
      return;
    }

    const stillExists = selectedDeviceId && devices.some((device) => device.id === selectedDeviceId);
    if (!stillExists) {
      setSelectedDeviceId(null);
    }
  }, [devices, selectedDeviceId]);

  useEffect(() => {
    let disposed = false;

    const syncRobotHealth = async () => {
      try {
        const health = await getOverallHealth();
        if (disposed) return;

        const robotHealth = health.devices.robot;
        if (!robotHealth) return;

        const isConnected = robotHealth.status === "connected";
        setDevices((prev) =>
          prev.map((device) =>
            device.type === "robot"
              ? {
                  ...device,
                  status: robotHealth.status,
                  reachable: isConnected,
                  onlineSince: isConnected ? device.onlineSince ?? new Date().toISOString() : device.onlineSince,
                }
              : device,
          ),
        );
      } catch {
        // Keep existing local state if backend health endpoint is temporarily unavailable.
      }
    };

    void syncRobotHealth();
    const intervalId = window.setInterval(() => {
      void syncRobotHealth();
    }, 3000);

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const handleDeleteDevice = (id: string) => {
    setDevices((prev) => prev.filter((d) => d.id !== id));
  };

  const handleEditDevice = (device: Device) => {
    setEditingDevice(device);
  };

  const handleAddOrUpdateDevice = (device: Device) => {
    setDevices((prev) => {
      const exists = prev.find((d) => d.id === device.id);
      if (exists) {
        return prev.map((d) => (d.id === device.id ? device : d));
      }
      return [...prev, device];
    });
  };

  const groupedDevices = devices.reduce((acc, device) => {
    const type = device.type;
    if (!acc[type]) acc[type] = [];
    acc[type].push(device);
    return acc;
  }, {} as Record<string, Device[]>);

  const groupOrder: string[] = ["robot", "gripper", "camera", "sensor"];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex flex-col px-1 pb-0 overflow-hidden h-full">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <h2 className="forgis-text-title font-normal uppercase text-[var(--gunmetal-50)] leading-none font-forgis-digit">
            Devices
          </h2>
          <AddDeviceDialog
            trigger={
              <Button variant="outline" size="sm" className="h-6 gap-1 px-1.5 forgis-text-detail">
                <Plus className="w-3 h-3" />
                Add
              </Button>
            }
            onAdd={handleAddOrUpdateDevice}
            editingDevice={editingDevice}
            onOpenChange={(open) => !open && setEditingDevice(null)}
          />
        </div>

        {/* Device list groups */}
        <div className={cn("overflow-y-auto -mx-3", selectedStep ? "shrink-0 max-h-[40%]" : "shrink-0 max-h-[38%]")}>
          {groupOrder.map((type) => {
            const group = groupedDevices[type];
            if (!group || group.length === 0) return null;

            return (
              <div key={type} className="mb-4 last:mb-0">
                <div className="px-3 mb-1">
                  <h3 className="forgis-text-detail font-medium uppercase text-[var(--gunmetal-50)] text-[10px] tracking-wider font-forgis-digit">
                    {type}s
                  </h3>
                </div>
                <DeviceList
                  devices={group}
                  compact
                  selectedId={selectedDeviceId}
                  onSelect={(device) => {
                    setSelectedDeviceId(device.id);
                    onOpenDeviceDetail?.(device);
                  }}
                  onDelete={handleDeleteDevice}
                  onEdit={handleEditDevice}
                />
              </div>
            );
          })}

          {/* Any other types not in groupOrder */}
          {Object.entries(groupedDevices).map(([type, group]) => {
            if (groupOrder.includes(type)) return null;
            return (
              <div key={type} className="mb-4 last:mb-0">
                <div className="px-3 mb-1">
                  <h3 className="forgis-text-detail font-medium uppercase text-[var(--gunmetal-50)] text-[10px] tracking-wider font-forgis-digit">
                    {type}s
                  </h3>
                </div>
                <DeviceList
                  devices={group}
                  compact
                  selectedId={selectedDeviceId}
                  onSelect={(device) => {
                    setSelectedDeviceId(device.id);
                    onOpenDeviceDetail?.(device);
                  }}
                  onDelete={handleDeleteDevice}
                  onEdit={handleEditDevice}
                />
              </div>
            );
          })}
        </div>

        {/* Node creator dialog */}
        <NodeCreatorDialog
          open={!!nodeCreatorOpen}
          onClose={() => onCloseNodeCreator?.()}
        />

        {/* Parameter editor (inline) */}
        {selectedStep && (
          <ParameterEditor
            selectedStep={selectedStep}
            onDeselectStep={onDeselectStep}
            onParamChange={onParamChange}
          />
        )}
      </div>
    </div>
  );
}
