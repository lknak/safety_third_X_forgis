import { Trash2, Pencil, Wifi, WifiOff, Clock, Tag } from "lucide-react";
import type { Device } from "@/types";
import { DEVICE_ICONS, STATUS_COLOR, STATUS_LABEL } from "@/constants/deviceConfig";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface DeviceListProps {
  devices: Device[];
  compact?: boolean;
  onDelete?: (id: string) => void;
  onEdit?: (device: Device) => void;
}

export function DeviceList({ devices, compact = false, onDelete, onEdit }: DeviceListProps) {
  if (devices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-1.5 py-5 text-muted-foreground">
        <span className="forgis-text-label font-forgis-body">No devices connected.</span>
      </div>
    );
  }

  const formatUptime = (isoString?: string) => {
    if (!isoString) return "N/A";
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  if (compact) {
    return (
      <div className="divide-y divide-border">
        {devices.map((device) => {
          const Icon = DEVICE_ICONS[device.type];
          const color = STATUS_COLOR[device.status];
          const label = STATUS_LABEL[device.status];
          return (
            <div key={device.id} className="flex flex-col p-3 group hover:bg-muted/30 transition-colors">
              <div className="flex items-center gap-2.5 mb-1">
                <div className="shrink-0 w-6 h-6 rounded-md bg-muted/50 flex items-center justify-center">
                  <Icon className="w-3.5 h-3.5 text-muted-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="forgis-text-detail font-bold text-foreground leading-tight truncate font-forgis-digit">
                    {device.name}
                  </div>
                  <div className="forgis-text-detail text-[var(--gunmetal-50)] truncate font-forgis-body">
                    {device.vendor} · {device.ip}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <span
                    className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0",
                      device.status === "warning" && "animate-pulse",
                    )}
                    style={{ background: color }}
                  />
                  <span className="forgis-text-detail font-bold" style={{ color }}>{label}</span>
                </div>
              </div>

              <div className="flex items-center justify-between mt-1 border-t border-border/30 pt-1.5">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    {device.reachable ? (
                      <Wifi size={10} className="text-[var(--status-healthy)]" />
                    ) : (
                      <WifiOff size={10} className="text-[var(--status-critical)]" />
                    )}
                    <span className="text-[9px] uppercase tracking-wider font-bold text-[var(--gunmetal-50)]">
                      {device.reachable ? "Reachable" : "Offline"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Clock size={10} className="text-[var(--gunmetal-50)]" />
                    <span className="text-[9px] uppercase tracking-wider text-[var(--gunmetal-50)]">
                      {formatUptime(device.onlineSince)}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {onEdit && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="w-6 h-6 text-muted-foreground hover:text-foreground"
                      onClick={(e) => {
                        e.stopPropagation();
                        onEdit(device);
                      }}
                    >
                      <Pencil className="w-3 h-3" />
                    </Button>
                  )}
                  {onDelete && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="w-6 h-6 text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(device.id);
                      }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="divide-y divide-border">
      {devices.map((device) => {
        const Icon = DEVICE_ICONS[device.type];
        const color = STATUS_COLOR[device.status];
        const label = STATUS_LABEL[device.status];
        return (
          <div key={device.id} className="flex flex-col group hover:bg-muted/20 transition-colors">
            <div className="flex items-center gap-3 px-6 py-3">
              <div className="shrink-0 w-8 h-8 rounded-md bg-muted/50 flex items-center justify-center">
                <Icon className="w-4.5 h-4.5 text-muted-foreground" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="forgis-text-label font-bold text-foreground leading-tight truncate">
                  {device.name}
                </div>
                <div className="forgis-text-caption text-muted-foreground truncate flex items-center gap-2">
                  <span>{device.vendor}</span>
                  <span className="w-1 h-1 rounded-full bg-border" />
                  <span className="font-mono">{device.ip}</span>
                </div>
              </div>

              <div className="flex flex-col items-end gap-1 px-4 border-l border-r border-border/50 min-w-[140px]">
                <div className="flex items-center gap-1.5 justify-end">
                  <div
                    className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0",
                      device.status === "warning" && "animate-pulse",
                    )}
                    style={{ background: color }}
                  />
                  <span className="forgis-text-caption font-bold uppercase tracking-wider" style={{ color }}>{label}</span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    {device.reachable ? (
                      <Wifi size={11} className="text-[var(--status-healthy)]" />
                    ) : (
                      <WifiOff size={11} className="text-[var(--status-critical)]" />
                    )}
                    <span className="text-[10px] uppercase font-medium text-[var(--gunmetal-50)]">
                      {device.reachable ? "Reachable" : "Unreachable"}
                    </span>
                  </div>
                  {device.firmwareVersion && (
                    <div className="flex items-center gap-1">
                      <Tag size={11} className="text-[var(--gunmetal-50)]" />
                      <span className="text-[10px] uppercase font-medium text-[var(--gunmetal-50)]">
                        v{device.firmwareVersion}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex flex-col items-end min-w-[120px] pl-4">
                <div className="text-[10px] uppercase font-bold text-[var(--gunmetal-50)] mb-0.5">Online Since</div>
                <div className="forgis-text-caption font-medium">{formatUptime(device.onlineSince)}</div>
              </div>

              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-4">
                {onEdit && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-9 h-9 text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      onEdit(device);
                    }}
                  >
                    <Pencil className="w-4 h-4" />
                  </Button>
                )}
                {onDelete && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-9 h-9 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(device.id);
                    }}
                  >
                    <Trash2 className="w-4.5 h-4.5" />
                  </Button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
