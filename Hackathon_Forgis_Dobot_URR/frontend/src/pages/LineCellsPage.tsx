import { useParams, useNavigate, Link } from "react-router-dom";
import { TopBar } from "@/components/layout/Topbar";
import {
    Breadcrumb,
    BreadcrumbList,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbSeparator,
    BreadcrumbPage
} from "@/components/ui/breadcrumb";
import { LINES, type Cell } from "@/constants/factoryData";
import { ChevronRight, LayoutGrid, Activity } from "lucide-react";

export default function LineCellsPage() {
    const { lineId } = useParams<{ lineId: string }>();
    const navigate = useNavigate();

    const line = LINES.find((l) => l.id === lineId);

    if (!line) {
        return (
            <div className="flex flex-col h-screen bg-background items-center justify-center">
                <h1 className="text-2xl font-bold text-[var(--gunmetal)]">Line not found</h1>
                <Link to="/" className="mt-4 text-[var(--orange)] hover:underline">Return to Overview</Link>
            </div>
        );
    }

    const getStatusColor = (status: Cell["status"]) => {
        switch (status) {
            case "healthy": return "var(--status-healthy)";
            case "warning": return "var(--status-warning)";
            case "critical": return "var(--status-critical)";
            case "offline": return "var(--status-offline)";
            default: return "var(--gunmetal-50)";
        }
    };

    const getStatusBg = (status: Cell["status"]) => {
        switch (status) {
            case "healthy": return "rgba(0, 221, 59, 0.1)";
            case "warning": return "rgba(253, 211, 88, 0.1)";
            case "critical": return "rgba(255, 90, 0, 0.1)";
            case "offline": return "rgba(136, 144, 147, 0.1)";
            default: return "transparent";
        }
    };

    return (
        <div className="flex flex-col h-screen overflow-hidden bg-background">
            <TopBar />

            {/* Breadcrumb Header */}
            <div className="flex items-center px-8 py-4 border-b border-border bg-card/80 backdrop-blur-panel">
                <Breadcrumb>
                    <BreadcrumbList>
                        <BreadcrumbItem>
                            <BreadcrumbLink asChild className="forgis-text-label font-forgis-body text-[var(--gunmetal-50)] no-underline">
                                <Link to="/">Forgis Factory</Link>
                            </BreadcrumbLink>
                        </BreadcrumbItem>
                        <BreadcrumbSeparator />
                        <BreadcrumbItem>
                            <BreadcrumbPage className="forgis-text-label font-forgis-body text-[var(--gunmetal)] font-bold">
                                {line.name}
                            </BreadcrumbPage>
                        </BreadcrumbItem>
                    </BreadcrumbList>
                </Breadcrumb>
            </div>

            <div className="px-8 pt-8 pb-4">
                <div className="flex items-center gap-3 mb-2">
                    <div className="p-2 rounded-lg bg-[var(--platinum)] text-[var(--orange)]">
                        <line.icon size={20} />
                    </div>
                    <h1 className="text-2xl font-bold tracking-tight text-[var(--gunmetal)]">
                        Line Components
                    </h1>
                </div>
                <p className="text-[var(--gunmetal-50)] max-w-2xl">
                    Detailed view of production cells for {line.name.split(":")[0]}. Select a specific cell to access real-time telemetry and robot path controls.
                </p>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 overflow-y-auto p-8 dot-grid-bg">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-7xl mx-auto">
                    {line.cells.map((cell) => (
                        <div
                            key={cell.id}
                            onClick={() => navigate(`/line/${line.id}/cell/${cell.id}`)}
                            className="group relative flex flex-col bg-card border border-border rounded-xl p-5 transition-all duration-300 hover:scale-[1.02] hover:shadow-xl hover:border-[var(--orange)] cursor-pointer overflow-hidden"
                        >
                            {/* Decorative Glow */}
                            <div
                                className="absolute -right-4 -top-4 w-24 h-24 blur-3xl opacity-0 group-hover:opacity-20 transition-opacity duration-500"
                                style={{ backgroundColor: getStatusColor(cell.status) }}
                            />

                            <div className="relative z-10 flex flex-col h-full">
                                <div className="flex items-start justify-between mb-4">
                                    <div className="flex items-center gap-2">
                                        <div className="p-2 rounded-md bg-[var(--platinum)] text-[var(--gunmetal-50)] group-hover:text-[var(--orange)] transition-colors">
                                            <LayoutGrid size={16} />
                                        </div>
                                        <span className="text-xs font-bold text-[var(--gunmetal-50)] uppercase tracking-widest">
                                            {cell.id.toUpperCase()}
                                        </span>
                                    </div>
                                    <div
                                        className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-tight"
                                        style={{ backgroundColor: getStatusBg(cell.status), color: getStatusColor(cell.status) }}
                                    >
                                        <div
                                            className="w-1.5 h-1.5 rounded-full animate-pulse-dot"
                                            style={{ backgroundColor: getStatusColor(cell.status) }}
                                        />
                                        {cell.status}
                                    </div>
                                </div>

                                <h3 className="text-lg font-bold text-[var(--gunmetal)] mb-1 group-hover:text-[var(--orange)] transition-colors">
                                    {cell.name}
                                </h3>
                                <p className="text-xs text-[var(--gunmetal-50)] mb-6">
                                    Ready for operations and remote adjustment.
                                </p>

                                <div className="mt-auto pt-4 border-t border-border/50 flex items-center justify-between text-[var(--gunmetal-50)] group-hover:text-[var(--gunmetal)] transition-colors">
                                    <div className="flex items-center gap-1.5 font-medium text-[10px] uppercase tracking-wider">
                                        <Activity size={12} className="text-[var(--orange)]" />
                                        Telemetry Active
                                    </div>
                                    <ChevronRight size={14} className="group-hover:translate-x-1 transition-transform" />
                                </div>
                            </div>

                            {/* Hover highlight border */}
                            <div className="absolute top-0 left-0 w-1 h-full bg-[var(--orange)] scale-y-0 group-hover:scale-y-100 transition-transform duration-300 origin-top" />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
