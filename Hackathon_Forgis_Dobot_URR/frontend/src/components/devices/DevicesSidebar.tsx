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

export function DevicesSidebar({
  selectedStep,
  onDeselectStep,
  onParamChange,
  nodeCreatorOpen,
  onCloseNodeCreator,
  onOpenDeviceDetail,
}: DevicesSidebarProps) {
  const [devices, setDevices] = useState<Device[]>(DEFAULT_DEVICES);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);

  useEffect(() => {
    if (devices.length === 0) {
      setSelectedDeviceId(null);
      return;
    }

    const stillExists =
      selectedDeviceId && devices.some((device: Device) => device.id === selectedDeviceId);
    if (!stillExists) {
      setSelectedDeviceId(null);
    }
  }, [devices, selectedDeviceId]);

  useEffect(() => {
    let disposed = false;

    const syncDeviceHealth = async () => {
      try {
        const health = await getOverallHealth();
        if (disposed || !health?.devices) return;

        const healthData = health.devices;

        setDevices((prev: Device[]) =>
          prev.map((device: Device) => {
            const updates: Partial<Device> = {};

            if (device.type === "robot" && healthData.robot) {
              const connected = healthData.robot.status === "connected";
              updates.status = healthData.robot.status;
              updates.reachable = connected;
              if (connected) updates.onlineSince = device.onlineSince ?? new Date().toISOString();
            } else if (device.type === "camera" && healthData.camera) {
              const connected = healthData.camera.status === "connected";
              updates.status = healthData.camera.status;
              updates.reachable = connected;
              if (connected) updates.onlineSince = device.onlineSince ?? new Date().toISOString();
            } else if (device.type === "gripper" && healthData.hand) {
              const connected = healthData.hand.status === "connected";
              updates.status = healthData.hand.status;
              updates.reachable = connected;
              if (connected) updates.onlineSince = device.onlineSince ?? new Date().toISOString();
            }

            if (Object.keys(updates).length > 0) {
              return { ...device, ...updates };
            }
            return device;
          })
        );
      } catch (err) {
        console.warn("Device health sync failed:", err);
      }
    };

    void syncDeviceHealth();
    const intervalId = window.setInterval(() => {
      void syncDeviceHealth();
    }, 3000);

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const handleDeleteDevice = (id: string) => {
    setDevices((prev: Device[]) => prev.filter((d: Device) => d.id !== id));
  };

  const handleEditDevice = (device: Device) => {
    setEditingDevice(device);
  };

  const handleAddOrUpdateDevice = (device: Device) => {
    setDevices((prev: Device[]) => {
      const exists = prev.find((d: Device) => d.id === device.id);
      if (exists) {
        return prev.map((d: Device) => (d.id === device.id ? device : d));
      }
      return [...prev, device];
    });
  };

  const groupedDevices = devices.reduce((acc: Record<string, Device[]>, device: Device) => {
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
            onOpenChange={(open: boolean) => !open && setEditingDevice(null)}
          />
        </div>

        {/* Device list groups */}
        <div
          className={cn(
            "overflow-y-auto min-h-0 -mx-3",
            selectedStep ? "shrink-0 max-h-[40%]" : "flex-1"
          )}
        >
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
                  onSelect={(device: Device) => {
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
                  onSelect={(device: Device) => {
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
