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

export function SettingsDialog() {
    const [open, setOpen] = useState(false);
    const [apiKey, setApiKey] = useState("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        const savedKey = localStorage.getItem("GEMINI_API_KEY");
        if (savedKey) setApiKey(savedKey);
    }, []);

    const handleSave = async () => {
        setSaving(true);
        try {
            // Save to local storage for persistence across reloads
            localStorage.setItem("GEMINI_API_KEY", apiKey);

            // Inform backend about the new key
            const response = await fetch("http://localhost:8000/api/config/gemini", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ gemini_api_key: apiKey }),
            });

            if (!response.ok) {
                throw new Error("Failed to update backend configuration");
            }

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
