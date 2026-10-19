import { initFrontendSecurity } from "./security";
import { bootstrapEmbed } from "./embed";
import { initLocalNav } from "./localNav";
import { initUgdAgent } from "./ugdAgent";

bootstrapEmbed();
initLocalNav();
initFrontendSecurity();
initUgdAgent();
