import { useState, useEffect, type ReactNode } from "react";
import type { Device, DeviceType } from "@/types";
import { BRANDS, EMPTY_FORM, type DeviceFormData } from "@/constants/deviceConfig";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface AddDeviceDialogProps {
  trigger: ReactNode;
  onAdd: (device: Device) => void;
  editingDevice?: Device | null;
  onOpenChange?: (open: boolean) => void;
}

export function AddDeviceDialog({ trigger, onAdd, editingDevice, onOpenChange: externalOnOpenChange }: AddDeviceDialogProps) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<DeviceFormData>(EMPTY_FORM);

  useEffect(() => {
    if (editingDevice) {
      setForm({
        type: editingDevice.type,
        brand: editingDevice.vendor,
        robotModel: editingDevice.type === "robot" ? editingDevice.name : "",
        name: editingDevice.name,
        apiEndpoint: editingDevice.ip,
        firmwareVersion: editingDevice.firmwareVersion || "",
        lastMaintenance: editingDevice.lastMaintenance || "",
      });
      setOpen(true);
    }
  }, [editingDevice]);

  const set = <K extends keyof DeviceFormData>(key: K, value: DeviceFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleTypeChange = (value: DeviceType) => {
    setForm((prev) => ({ ...prev, type: value, brand: "", robotModel: "" }));
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    externalOnOpenChange?.(next);
    if (!next) setForm(EMPTY_FORM);
  };

  const handleAdd = () => {
    const newDevice: Device = {
      id: editingDevice?.id || `device-${Date.now()}`,
      name: form.name.trim(),
      vendor: form.brand,
      type: form.type as DeviceType,
      status: editingDevice?.status || "connected",
      ip: form.apiEndpoint.trim() || "192.168.1.10",
      reachable: editingDevice ? editingDevice.reachable : true,
      onlineSince: editingDevice ? editingDevice.onlineSince : new Date().toISOString(),
      firmwareVersion: form.firmwareVersion.trim() || undefined,
      lastMaintenance: form.lastMaintenance || undefined,
    };
    onAdd(newDevice);
    handleOpenChange(false);
  };

  const canAdd =
    form.type !== "" &&
    form.brand !== "" &&
    form.name.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>

      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{editingDevice ? "Edit Device" : "Add Device"}</DialogTitle>
          <DialogDescription>
            {editingDevice ? "Update the device configuration." : "Configure a device to connect to this station."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="device-type">Device Type</Label>
              <Select
                value={form.type}
                onValueChange={(v) => handleTypeChange(v as DeviceType)}
              >
                <SelectTrigger id="device-type">
                  <SelectValue placeholder="Select type..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="robot">Robot</SelectItem>
                  <SelectItem value="gripper">Gripper</SelectItem>
                  <SelectItem value="camera">Camera</SelectItem>
                  <SelectItem value="sensor">Sensor</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="device-brand">Brand</Label>
              <Select
                value={form.brand}
                onValueChange={(v) => set("brand", v)}
                disabled={!form.type}
              >
                <SelectTrigger id="device-brand">
                  <SelectValue placeholder={form.type ? "Select brand..." : "Select a type first"} />
                </SelectTrigger>
                <SelectContent>
                  {form.type &&
                    BRANDS[form.type].map((brand) => (
                      <SelectItem key={brand} value={brand}>
                        {brand}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="device-name">Device Name</Label>
            <Input
              id="device-name"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Robot_01, PLC_Main"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="api-endpoint">IP / Endpoint</Label>
              <Input
                id="api-endpoint"
                value={form.apiEndpoint}
                onChange={(e) => set("apiEndpoint", e.target.value)}
                placeholder="e.g. 192.168.1.10"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="firmware">Firmware</Label>
              <Input
                id="firmware"
                value={form.firmwareVersion}
                onChange={(e) => set("firmwareVersion", e.target.value)}
                placeholder="v1.0.0"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="maintenance">Last Maintenance</Label>
            <Input
              id="maintenance"
              type="date"
              value={form.lastMaintenance}
              onChange={(e) => set("lastMaintenance", e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!canAdd}
            onClick={handleAdd}
            className="bg-primary text-primary-foreground hover:bg-primary/80"
          >
            {editingDevice ? "Save Changes" : "Add Device"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
