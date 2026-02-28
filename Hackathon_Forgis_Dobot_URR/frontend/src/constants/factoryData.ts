import { Factory, Cpu, ShieldCheck, Box, Truck, Settings } from "lucide-react";

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
            { id: "c1-2", name: "Vision", status: "healthy" },
            { id: "c1-3", name: "Sorting", status: "warning" },
            { id: "c1-4", name: "Labeling", status: "healthy" },
        ],
    },
    {
        id: "line-2",
        name: "Line 2: Precision Assembly",
        description: "Multi-robot cooperative assembly for complex electronic components.",
        icon: Cpu,
        cells: [
            { id: "c2-1", name: "Pick-up", status: "healthy" },
            { id: "c2-2", name: "Alignment", status: "healthy" },
            { id: "c2-3", name: "Fastening", status: "healthy" },
        ],
    },
    {
        id: "line-3",
        name: "Line 3: Quality Assurance",
        description: "End-of-line testing station with 3D scanning and tolerance verification.",
        icon: ShieldCheck,
        cells: [
            { id: "c3-1", name: "Scanning", status: "healthy" },
            { id: "c3-2", name: "Testing", status: "healthy" },
            { id: "c3-3", name: "Validation", status: "healthy" },
        ],
    },
    {
        id: "line-4",
        name: "Line 4: Final Packaging",
        description: "Automated boxing, cushioning, and palletizing for shipment.",
        icon: Box,
        cells: [
            { id: "c4-1", name: "Boxing", status: "healthy" },
            { id: "c4-2", name: "Sealing", status: "healthy" },
            { id: "c4-3", name: "Palletizing", status: "critical" },
        ],
    },
    {
        id: "line-5",
        name: "Line 5: Logistics & Dispatch",
        description: "AGV coordination and smart storage allocation system.",
        icon: Truck,
        cells: [
            { id: "c5-1", name: "Loading", status: "healthy" },
            { id: "c5-2", name: "Routing", status: "healthy" },
        ],
    },
    {
        id: "line-6",
        name: "Line 6: Auxiliary Maintenance",
        description: "Diagnostic and preventative maintenance support station.",
        icon: Settings,
        cells: [
            { id: "c6-1", name: "Diagnostics", status: "healthy" },
            { id: "c6-2", name: "Lubrication", status: "offline" },
        ],
    },
];
