/****************************************************************************
 * Copyright (C) 2009-2011 Dimok
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 ****************************************************************************/
#include "FTPServerSettingsMenu.h"
#include "Prompts/PromptWindows.h"
#include "network/networkops.h"
#include "Settings.h"

FTPServerSettingsMenu::FTPServerSettingsMenu(GuiFrame *r)
	: SettingsMenu(tr("FTP Server Settings"), r)
{
	SetupOptions();
}

FTPServerSettingsMenu::~FTPServerSettingsMenu()
{
}

void FTPServerSettingsMenu::SetupOptions()
{
	int i = 0;

	options.SetName(i++, tr("Auto Start:"));
	options.SetName(i++, tr("Password:"));
	options.SetName(i++, tr("FTP Port:"));
	options.SetName(i++, tr("Username:"));
	options.SetName(i++, tr("Anonymous Access:"));
	options.SetName(i++, tr("Idle Timeout (seconds):"));

	SetOptionValues();
}

void FTPServerSettingsMenu::SetOptionValues()
{
	int i = 0;

	if(Settings.FTPServer.AutoStart)
		options.SetValue(i++, tr("ON"));
	else
		options.SetValue(i++, tr("OFF"));

	if (strcmp(Settings.FTPServer.Password, "") != 0)
		options.SetValue(i++,"********");
	else
		options.SetValue(i++," ");

	options.SetValue(i++,"%i", Settings.FTPServer.Port);
	options.SetValue(i++,"%s", Settings.FTPServer.User);
	options.SetValue(i++, Settings.FTPServer.Anonymous ? tr("ON (read-only)") : tr("OFF"));
	options.SetValue(i++,"%u", Settings.FTPServer.IdleTimeout);

}

void FTPServerSettingsMenu::OnOptionClick(GuiOptionBrowser *sender UNUSED, int option)
{
	char entered[300];
	int result = 0;

	switch (option)
	{
		case 0:
			Settings.FTPServer.AutoStart = (Settings.FTPServer.AutoStart+1) % 2;
			break;
		case 1:
			entered[0] = 0;
			result = OnScreenKeyboard(entered, sizeof(Settings.FTPServer.Password)-1);
			if(result)
				snprintf(Settings.FTPServer.Password, sizeof(Settings.FTPServer.Password), "%s", entered);
			break;
		case 2:
			snprintf(entered, sizeof(entered), "%d", Settings.FTPServer.Port);
			result = OnScreenKeyboard(entered, 149);
			if(result)
				{ int port = atoi(entered); if (port >= 1 && port <= 65535) Settings.FTPServer.Port = port; }
			break;
		case 3:
			snprintf(entered,sizeof(entered),"%s",Settings.FTPServer.User);
			if (OnScreenKeyboard(entered,sizeof(Settings.FTPServer.User)-1))
				snprintf(Settings.FTPServer.User,sizeof(Settings.FTPServer.User),"%s",entered);
			break;
		case 4:
			Settings.FTPServer.Anonymous = !Settings.FTPServer.Anonymous;
			break;
		case 5:
			snprintf(entered,sizeof(entered),"%u",Settings.FTPServer.IdleTimeout);
			if (OnScreenKeyboard(entered,5)) {
				int seconds = atoi(entered);
				if (seconds >= 1 && seconds <= 86400) Settings.FTPServer.IdleTimeout = seconds;
			}
			break;
		default:
			break;
	}

	SetOptionValues();
}
