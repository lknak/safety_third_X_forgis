import { useState, useEffect } from "react";
import { Settings } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { postJson } from "@/api/httpClient";

let didSyncStoredApiKey = false;

export function SettingsDialog() {
    const [open, setOpen] = useState(false);
    const [apiKey, setApiKey] = useState("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        const savedKey = localStorage.getItem("GEMINI_API_KEY")?.trim() ?? "";
        if (!savedKey) return;

        setApiKey(savedKey);

        // Re-sync persisted key on app load (backend may have restarted).
        if (didSyncStoredApiKey) return;

        void postJson<{ status: string; message: string }>("/config/gemini", {
            gemini_api_key: savedKey,
        })
            .then(() => {
                didSyncStoredApiKey = true;
            })
            .catch((error) => {
                console.warn("Failed to re-sync Gemini API key on startup:", error);
            });
    }, []);

    const handleSave = async () => {
        const normalizedKey = apiKey.trim();
        if (!normalizedKey) {
            alert("Please enter a valid Gemini API key.");
            return;
        }

        setSaving(true);
        try {
            // Use same-origin API path so SSH/VSCode port forwarding works.
            await postJson<{ status: string; message: string }>("/config/gemini", {
                gemini_api_key: normalizedKey,
            });

            // Save locally for persistence after backend update succeeds.
            localStorage.setItem("GEMINI_API_KEY", normalizedKey);
            didSyncStoredApiKey = true;
            setApiKey(normalizedKey);

            setOpen(false);
        } catch (error) {
            console.error("Error saving settings:", error);
            alert("Failed to save settings. Check console for details.");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <button
                    type="button"
                    className="p-1 hover:opacity-80 transition-opacity focus:outline-none"
                    aria-label="Settings"
                >
                    <Settings size={12} className="text-white" />
                </button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>System Settings</DialogTitle>
                    <DialogDescription>
                        Configure your global AI settings here.
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                        <Label htmlFor="api-key">Google Gemini API Key</Label>
                        <Input
                            id="api-key"
                            type="password"
                            placeholder="Enter your API key..."
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                        />
                        <p className="text-[10px] text-muted-foreground">
                            Your key is used for flow generation, vision analysis, and reasoning.
                        </p>
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setOpen(false)}>
                        Cancel
                    </Button>
                    <Button onClick={handleSave} disabled={saving}>
                        {saving ? "Saving..." : "Save Configuration"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
