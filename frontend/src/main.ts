import { initFrontendSecurity } from "./security";
import { bootstrapEmbed } from "./embed";
import { initUgdAgent } from "./ugdAgent";

bootstrapEmbed();
initFrontendSecurity();
initUgdAgent();
