#ifndef BACKUP_DOMAIN_ACCESS_H
#define BACKUP_DOMAIN_ACCESS_H

#include <Arduino.h>

/**
 * @brief Temporarily allow RTC/backup writes without revoking another owner's access.
 *
 * STM32RTC enables backup-domain access during begin() and expects it to remain
 * enabled for its date/time and alarm setters. Preserve the entry DBP state,
 * including for nested guards; never unconditionally disable it on return.
 */
class BackupDomainAccess
{
public:
    BackupDomainAccess()
    {
        __HAL_RCC_PWR_CLK_ENABLE();
        wasEnabled_ = (PWR->CR & PWR_CR_DBP) != 0U;
        HAL_PWR_EnableBkUpAccess();
        __HAL_RCC_RTC_ENABLE();
    }

    ~BackupDomainAccess()
    {
        if (!wasEnabled_)
        {
            HAL_PWR_DisableBkUpAccess();
        }
    }

    BackupDomainAccess(const BackupDomainAccess&) = delete;
    BackupDomainAccess& operator=(const BackupDomainAccess&) = delete;

private:
    bool wasEnabled_ = false;
};

#endif
