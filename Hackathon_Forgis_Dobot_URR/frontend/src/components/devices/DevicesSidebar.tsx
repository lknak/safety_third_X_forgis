import { useState } from "react";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import type { Device, SelectedStep } from "@/types";
import { DEFAULT_DEVICES } from "@/constants/deviceConfig";
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
}

export function DevicesSidebar({ selectedStep, onDeselectStep, onParamChange, nodeCreatorOpen, onCloseNodeCreator }: DevicesSidebarProps) {
  const [devices, setDevices] = useState<Device[]>(DEFAULT_DEVICES);
  const [collapsed, setCollapsed] = useState(false);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);

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
    <div
      className={cn(
        "relative flex flex-col bg-card border-r border-border transition-[width] duration-250 ease-in-out overflow-hidden",
        collapsed ? "w-9" : "w-64"
      )}
    >
      {/* Toggle */}
      <button
        className="absolute top-2 right-1 z-10 flex items-center justify-center w-7 h-7 rounded bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer border-none"
        onClick={() => setCollapsed((c) => !c)}
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>

      {!collapsed && (
        <div className="flex flex-col pt-10 px-3 pb-0 overflow-hidden h-full">
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
          <div className={cn("overflow-y-auto -mx-3", selectedStep ? "shrink-0 max-h-[40%]" : "flex-1")}>
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
                  <DeviceList devices={group} compact onDelete={handleDeleteDevice} onEdit={handleEditDevice} />
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
                  <DeviceList devices={group} compact onDelete={handleDeleteDevice} onEdit={handleEditDevice} />
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
      )}
    </div>
  );
}
