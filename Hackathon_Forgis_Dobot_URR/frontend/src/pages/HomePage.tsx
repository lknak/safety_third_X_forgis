import { useNavigate } from "react-router-dom";
import { TopBar } from "@/components/layout/Topbar";
import { ChevronRight } from "lucide-react";
import { LINES, type Cell } from "@/constants/factoryData";

export default function HomePage() {
    const navigate = useNavigate();

    const getStatusColor = (status: Cell["status"]) => {
        switch (status) {
            case "healthy": return "var(--status-healthy)";
            case "warning": return "var(--status-warning)";
            case "critical": return "var(--status-critical)";
            case "offline": return "var(--status-offline)";
            default: return "var(--gunmetal-50)";
        }
    };

    return (
        <div className="flex flex-col h-screen overflow-hidden bg-background">
            <TopBar />

            {/* Hero / Header Section */}
            <div className="px-8 pt-8 pb-4">
                <h1 className="text-3xl font-bold tracking-tight text-[var(--gunmetal)] mb-2">
                    Factory Overview
                </h1>
                <p className="text-[var(--gunmetal-50)] max-w-2xl">
                    Monitor and control production lines across the facility. Select a line to view detailed diagnostics and manage robotic operations.
                </p>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 overflow-y-auto p-8 dot-grid-bg">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-7xl mx-auto">
                    {LINES.map((line) => (
                        <div
                            key={line.id}
                            onClick={() => navigate(`/line/${line.id}`)}
                            className="group relative flex flex-col bg-card border border-border rounded-2xl p-6 transition-all duration-300 hover:scale-[1.02] hover:shadow-2xl hover:border-[var(--orange)] cursor-pointer overflow-hidden"
                        >
                            {/* Decorative Gradient Background */}
                            <div className="absolute inset-0 bg-gradient-to-br from-transparent to-[var(--platinum)] opacity-0 group-hover:opacity-100 transition-opacity duration-300" />

                            <div className="relative z-10">
                                <div className="flex items-start justify-between mb-4">
                                    <div className="p-3 rounded-xl bg-[var(--platinum)] text-[var(--orange)] group-hover:bg-[var(--orange)] group-hover:text-white transition-colors duration-300">
                                        <line.icon size={24} />
                                    </div>
                                    <ChevronRight
                                        size={20}
                                        className="text-[var(--gunmetal-10)] group-hover:text-[var(--orange)] translate-x-0 group-hover:translate-x-1 transition-all"
                                    />
                                </div>

                                <h3 className="text-lg font-bold text-[var(--gunmetal)] mb-2 group-hover:text-[var(--orange)] transition-colors">
                                    {line.name}
                                </h3>
                                <p className="text-sm text-[var(--gunmetal-50)] mb-6 line-clamp-2">
                                    {line.description}
                                </p>

                                <div className="mt-auto">
                                    <div className="flex flex-wrap gap-2">
                                        {line.cells.map((cell) => (
                                            <div
                                                key={cell.id}
                                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--platinum)] border border-transparent group-hover:border-[var(--gunmetal-10)] transition-all"
                                                title={`${cell.name}: ${cell.status}`}
                                            >
                                                <div
                                                    className="w-2 h-2 rounded-full animate-pulse-dot"
                                                    style={{ backgroundColor: getStatusColor(cell.status) }}
                                                />
                                                <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--gunmetal-50)]">
                                                    {cell.name}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            {/* Bottom Accent Line */}
                            <div className="absolute bottom-0 left-0 w-full h-1 bg-[var(--orange)] scale-x-0 group-hover:scale-x-100 transition-transform duration-500 origin-left" />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
