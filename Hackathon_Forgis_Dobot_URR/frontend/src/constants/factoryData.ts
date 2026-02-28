import { Factory } from "lucide-react";

export interface Cell {
    id: string;
    name: string;
    status: "healthy" | "warning" | "critical" | "offline";
}

export interface Line {
    id: string;
    name: string;
    description: string;
    icon: any; // Lucide icon component
    cells: Cell[];
}

export const LINES: Line[] = [
    {
        id: "line-1",
        name: "Line 1: Labeling & Sorting",
        description: "High-speed vision-guided sorting and automated labeling system.",
        icon: Factory,
        cells: [
            { id: "c1-1", name: "Infeed", status: "healthy" },
        ],
    },
];
