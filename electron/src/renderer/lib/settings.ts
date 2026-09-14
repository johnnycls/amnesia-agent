import type { Config } from '../../shared/types';

export interface SettingsForm { model: string; apiKey: string; baseUrl: string; providerParams: string; timeout: string; outputLimit: string; contextLimit: string; }
export const emptySettings: SettingsForm = { model: '', apiKey: '', baseUrl: '', providerParams: '{}', timeout: '1800', outputLimit: '262144', contextLimit: '1000' };
export function configToForm(config: Config): SettingsForm { return { model: config.model, apiKey: '', baseUrl: config.base_url ?? '', providerParams: JSON.stringify(config.provider_params ?? {}, null, 2), timeout: String(config.command_timeout_seconds), outputLimit: String(config.max_command_output_bytes), contextLimit: String(config.max_context_message_chars) }; }
